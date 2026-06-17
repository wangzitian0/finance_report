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
