# LLM Provider Abstraction SSOT

> **SSOT Key**: `llm_provider_abstraction`
> **Core Definition**: How the backend talks to language models — the three
> orthogonal axes (protocol family × model × scene), the scene→model binding, and
> the at-rest encryption of provider secrets.

This document owns the *vocabulary and contracts* of the LLM layer. It does **not**
own the concrete values (which provider, which key, which model per scene) — those
are operational data that live in the database (EPIC-023 EPIC B) and are edited at
runtime. The code-level contract is `apps/backend/src/llm/common`.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Contract (types/protocols)** | `apps/backend/src/llm/common/` | Frozen value types + protocols both halves build against |
| **Secret cipher** | `apps/backend/src/llm/common/secrets.py` | Fernet/MultiFernet encryption of provider API keys at rest |
| **Encryption key** | `LLM_ENCRYPTION_KEYS` (env/Vault) | Project-level symmetric key(s), newest first |
| **Provider instances + scene bindings** | DB tables `llm_provider`, `llm_scene_binding` (EPIC B) | Runtime-editable configuration values |
| **Client / catalogue / usage impl** | `apps/backend/src/llm/` (EPIC A) | litellm-backed implementations of the protocols (usage meter counts requests/tokens, no cost) |

---

## 2. <a id="axes"></a>The Three Orthogonal Axes

Model usage is described by three axes that never collapse into one another.
Adding a model touches only axis 2; re-pointing a feature touches only the
binding; onboarding a vendor touches only axis 1.

### Axis 1 — Protocol family

Exactly three families, because these three are the universally-compatible wire
protocols. Every concrete vendor maps onto one of them:

| Family | Spoken by (examples) |
|--------|----------------------|
| `openai-compatible` | OpenAI, Z.AI/GLM, DeepSeek, a local vLLM (custom `api_base`) |
| `anthropic-compatible` | Claude (native Messages API) |
| `openrouter-compatible` | OpenRouter (adds `:free` tier, provider routing, extra headers) |

A *provider instance* is `(protocol_family, api_base?, api_key, label)`. The
litellm client turns it into a `provider/model` call string.

### Axis 2 — Model

A **dynamic catalogue** that can be much larger than the bound set. Each entry
(`ModelSpec`) carries its `provider_id`, `modalities` (text/image/pdf/file),
`is_free`, and pricing. Catalogue loading and free-tier flagging belong to the
`CatalogProvider` (EPIC A).

### Axis 3 — Scene

The fixed, code-defined set of call sites. Adding or renaming a scene is a
contract change (update this list and `src/llm/common/types.py:Scene`):

| Scene | Where |
|-------|-------|
| `extraction.ocr` | Dedicated OCR / layout parsing |
| `extraction.vision` | Vision-model fallback for image/PDF statements |
| `extraction.json` | Structured-JSON extraction pass |
| `advisor.chat` | AI advisor conversational replies |
| `statement.summary` | Statement summary generation |

### Binding — Scene × Model

`SceneBinding` resolves a scene to `model_id` plus per-scene parameters:
`reasoning` (depth), `prefer_free`, `fallback_model_ids`, `max_tokens`. This is
the configurable surface — swapping the model for `extraction.vision` is one
binding edit, independent of every other scene.

---

## 3. <a id="secrets"></a>Secret Encryption & Rotation

Provider API keys are stored in the database, so they are encrypted at rest with
a project-level key supplied via `LLM_ENCRYPTION_KEYS` (env/Vault), using Fernet
wrapped in `MultiFernet`:

- Keys are comma-separated, **newest first**. Index 0 encrypts; all keys are
  tried on decrypt, so an old ciphertext keeps decrypting after a new key lands.
- Each stored secret records the `key_version` that sealed it.
- **Rotation is one pass**: prepend a new key, re-encrypt every stored secret via
  `SecretCipher.rotate()` (the row loop lives in the DB layer), then drop the old
  key once every row carries the new `key_version`.

When `LLM_ENCRYPTION_KEYS` is empty, DB-backed provider secrets fail closed
(`build_cipher()` raises `LLMConfigError`); env/Vault-only provider configuration
still works.

---

## 4. <a id="config-flow"></a>Configuration Flow & First-Run

The client resolves a scene through a `ConfigSource`. EPIC A ships an env-backed
source; EPIC B swaps in a DB-backed one without the client changing. When
`ConfigSource.is_configured()` is `False` (no provider exists), the frontend
shows a first-run modal asking the user to add a provider before any AI feature
runs.

---

## 5. <a id="cassettes"></a>Record/Replay Cassettes (deterministic CI)

LLM calls are made **deterministic in CI** via a record/replay cassette layer
(`apps/backend/src/llm/cassette.py`) exposed through two chokepoints:
`client.cassette_completion` (non-streaming) and the **streaming bridge**
`client.litellm_stream` (the real extraction transport — see below). A *cassette*
is a committed JSON file under `apps/backend/tests/fixtures/llm_cassettes/`
holding the semantic request fingerprint and the frozen provider response —
reviewed in the diff.

### Modes — `LLM_CASSETTE_MODE`

| Mode | Where | Behaviour |
|------|-------|-----------|
| `replay` | **CI default** | Read-only from cassettes; **no API key, no network**. A cache MISS is a **hard failure** (`CassetteMiss`) with an actionable batch summary (`N cassette(s) need re-record: …; run make llm-record`) — it never falls back to the network. |
| `record` | local, with a provider key | Real provider call **and** write/update the cassette. Re-recording an unchanged request is idempotent (identical bytes). |
| `off` | local dev default | Normal live call, no cassette involvement. |

An unknown mode value fails closed (`LLMConfigError`) rather than silently
behaving like `off`. Re-record with **`make llm-record`** (or `pytest
--llm-record`); it is **provider-agnostic** — any provider key works, not only
the GLM plan.

### Fingerprint — model-id-agnostic

`key = sha256(normalize(role + messages + decode params + image-bytes hash))`.
It is computed on the *semantic request and modality role*, **NOT the exact model
id**, so bumping `glm-5.1 → 5.2` does not invalidate every cassette — refreshing
content is a re-record, the key is stable. Volatile fields (timestamps, random
request ids) are stripped before hashing; image content is reduced to a sha256 of
its bytes so transport encoding does not change the key. Only provably
output-irrelevant fields are stripped — any byte the provider would see changes
the key.

### Tagging — determinism ≠ correctness

Each cassette is tagged:

- **`correctness`** — its frozen response was validated against fixture
  ground-truth *at record time*. A `correctness` cassette **refuses to record**
  (`CassetteValidationError`) if validation fails or no validator is supplied — a
  frozen-wrong response would make CI green while asserting the LLM read numbers
  it never read. A test declares this via `tag=CassetteTag.CORRECTNESS` plus a
  `validator`.
- **`flow-only`** — asserts response *handling* only; it never claims the LLM read
  numbers correctly. The default tag.

### Streaming bridge — the real extraction transport

The real extraction transport is **streaming** (`services/ai_streaming.stream_ai_json`
→ `client.litellm_stream` → `accumulate_stream`), and both text and
default-config vision (`OCR_MODEL == VISION_MODEL`, layout parser skipped) flow
through it. `litellm_stream` is cassette-aware **while preserving streaming**:

- **`off`** — the prior live `litellm.acompletion(stream=True)` passthrough,
  byte-for-byte (deltas arrive as they stream). Prod/staging run `off`, so the
  staging `-m llm` live gate stays real and untouched.
- **`record`** — the real streaming call, accumulating the full text, then a
  cassette is frozen (storing the accumulated text under `stream_text`; a
  `correctness` tag validates the accumulated text first) and the text is yielded.
- **`replay`** — fingerprint + lookup with **no key/network**; a HIT synthesises
  the stream from the frozen text (one chunk), a MISS is a hard `CassetteMiss`.

The fingerprint **role** is derived from the messages — `vision` if any message
carries an image part, else `text` — so callers need no change and text vs vision
key distinctly. The non-default raw-httpx layout path
(`services/extraction/_ocr.py`) bypasses this bridge and is a known out-of-scope
gap. Wiring the first batch of extraction tests onto replay is scaffolded under
`apps/backend/tests/extraction/test_extraction_cassette_replay.py` (skipped via
the `needs_real_cassette` marker until the operator records real cassettes with
`make llm-record`).

### Scope (anti-false-confidence)

Record/replay is **regression protection for KNOWN inputs only**. It does **not**
discover new real-world document shapes — that stays the staging real-doc audit
loop — and **CI green ≠ a real unknown statement works**. Provider-specific
correctness is the staging `-m llm` gate's job, not the cassette tests'.
