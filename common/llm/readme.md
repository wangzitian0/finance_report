# `llm` — provider-abstraction bounded context

> One package owning the whole LLM concept: the **prose SSOT for the LLM
> provider abstraction** (this file) **and**, after the code cutover (#1426), the
> conforming implementation. This readme is the single registered owner of the
> LLM-layer vocabulary and contracts — the three orthogonal axes
> ([§The Three Orthogonal Axes](#axes)), the scene→model binding, the at-rest
> encryption of provider secrets, and the record/replay cassette layer
> ([§Record/Replay Cassettes](#cassettes)) — internalized here from the retired
> `docs/ssot/llm.md` per the package-migration standard
> ([`../meta/migration-standard.md`](../meta/migration-standard.md), step 3 "SSOT
> internalized").
>
> The conforming backend implementation lives at
> [`apps/backend/src/llm/`](../../apps/backend/src/llm/) (the code cutover #1426
> homes it under the package shape).

# LLM Provider Abstraction SSOT

> **SSOT Key**: `llm_provider_abstraction`
> **Core Definition**: How the backend talks to language models — the three
> orthogonal axes (protocol family × model × scene), the scene→model binding, and
> the at-rest encryption of provider secrets.

This document owns the *vocabulary and contracts* of the LLM layer. It does **not**
own the concrete values (which provider, which key, which model per scene) — those
are operational data that live in the database (EPIC-023 EPIC B) and are edited at
runtime. The code-level contract is `apps/backend/src/llm/base`.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Contract (types/protocols)** | `apps/backend/src/llm/base/` | Frozen value types + protocols both halves build against |
| **Secret cipher** | `apps/backend/src/llm/base/secrets.py` | Fernet/MultiFernet encryption of provider API keys at rest |
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
| `google-gemini` | Google Gemini (AI Studio / Vertex; native endpoint, accepts a whole PDF as one `file` part — no per-page image rendering — and a high output ceiling, so it extracts large/scanned statements that the image-render path truncates). Enable with `AI_PROVIDER=gemini` + `GEMINI_API_KEY`. DB-stored Gemini providers need an `llm_protocol_family_enum` migration; the env path works today. |

A *provider instance* is `(protocol_family, api_base?, api_key, label)`. The
litellm client turns it into a `provider/model` call string.

### Axis 2 — Model

A **dynamic catalogue** that can be much larger than the bound set. Each entry
(`ModelSpec`) carries its `provider_id`, `modalities` (text/image/pdf/file),
`is_free`, and pricing. Catalogue loading and free-tier flagging belong to the
`CatalogProvider` (EPIC A).

### Axis 3 — Scene

The fixed, code-defined set of call sites. Adding or renaming a scene is a
contract change (update this list and `src/llm/base/types.py:Scene`):

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
is a committed JSON file under `common/testing/fixtures/llm_cassettes/`
(the `testing` package's fixture home) holding the semantic request fingerprint
and the frozen provider response — reviewed in the diff.

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

The real extraction transport is **streaming** (`extension/streaming.stream_ai_json`
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
(`src/extraction/extension/_ocr.py`) bypasses this bridge and is a known out-of-scope
gap. Wiring the first batch of extraction tests onto replay is scaffolded under
`apps/backend/tests/extraction/test_extraction_cassette_replay.py` (skipped via
the `needs_real_cassette` marker until the operator records real cassettes with
`make llm-record`).

### Scope (anti-false-confidence)

Record/replay is **regression protection for KNOWN inputs only**. It does **not**
discover new real-world document shapes — that stays the staging real-doc audit
loop — and **CI green ≠ a real unknown statement works**. Provider-specific
correctness is the staging `-m llm` gate's job, not the cassette tests'.

---

## 6. <a id="cassette-graded-eval"></a>Cassette Graded Field-Accuracy Eval + Drift Ratchet

> SSOT owner for the **graded LLM extraction eval** over committed cassettes
> (EPIC-023 AC23.8, issue #1307) — internalized here from the retired
> `docs/ssot/cassette-graded-eval.md` per the package-migration standard
> ([`../meta/migration-standard.md`](../meta/migration-standard.md), step 3 "SSOT
> internalized"). The balance-chain integrity gate ([§Record/Replay
> Cassettes](#cassettes), AC23.7) is the *consistency* oracle; this is the
> *accuracy* oracle.

### 6.1 Why a graded eval (what the balance gate cannot see)

The committed record/replay cassettes are gated today by the **balance-chain
invariant** `opening + Σ amounts ≈ closing` (`tools/check_llm_cassettes.py`,
AC23.7). That catches an **inconsistent** re-recording, but it is blind to
**inaccuracy**: an LLM that reads `50` as `150` — or swaps two transaction
amounts so the net is unchanged — still satisfies the chain. Such a cassette is
*plausible but wrong*.

This graded eval scores each committed statement cassette **per field** against a
known-correct **ground-truth** artifact, producing a numeric `[0, 1]` accuracy
score per case, and ratchets a per-case **score floor** that may only go **UP**.
The gate fails CI when a refreshed cassette regresses a case below its floor —
including the "balance still reconciles but a field is now wrong" case.

### 6.2 Ground-truth source (synthetic only)

Each scored cassette `<fingerprint>.json` has a sibling ground-truth manifest
`common/testing/fixtures/llm_cassettes/ground_truth/<fingerprint>.truth.json`:

```json
{
  "synthetic": true,
  "modality": "text",
  "institution_class": "generic",
  "edge_condition": "happy_path",
  "expected": { "opening_balance": "...", "closing_balance": "...", "transactions": [ ... ] }
}
```

- **Data hygiene (AC, enforced):** every ground-truth artifact MUST set
  `"synthetic": true`. The inputs are **synthetic / anonymised** — never real
  financial data. The test `test_AC23_8_6_ground_truth_artifacts_are_synthetic`
  enforces the flag.
- `expected` carries the known-correct field values; the matching cassette
  supplies the LLM's frozen extraction to score against it.

### 6.3 Scoring & normalisation

A case score is the fraction of **scored fields** that match ground truth:

| Field | Match rule |
|-------|-----------|
| `opening_balance`, `closing_balance` | Decimal equality (never float) |
| transaction `amount` | Decimal equality (`"5.00" == 5 == 5.0`) |
| transaction `date` | ISO `YYYY-MM-DD` (slash forms normalised) |
| transaction `description` | case-folded, whitespace-collapsed |

A missing expected transaction row scores its fields as wrong; an **invented**
extra row is penalised as fully wrong. Money is compared as `Decimal`
end-to-end so `0.10 × 3 == 0.30` holds exactly.

### 6.4 Ratchet (floor only goes up)

The per-case floor is persisted as sorted, line-oriented JSONL at
`common/testing/fixtures/cassette-eval-baseline.jsonl` (one case per line,
`merge=union` in `.gitattributes` so PRs ratcheting different cases auto-merge).
This mirrors the established AC behavioural-score ratchet
(`docs/ssot/ac-score-baseline.jsonl`, `common/testing/check_ac_score_baseline.py`):

- **Gate:** `tools/check_cassette_graded_eval.py` fails if any case scores below
  its floor (minus a tiny epsilon), if a baselined case lost its floor, **or if a
  committed case has no floor at all** — so adding a case (or accidentally
  deleting its baseline line) cannot silently disable the ratchet while CI stays
  green.
- **Raise only:** `--update` raises the floor to the current scores and never
  lowers it; it adopts new cases (the sanctioned way to baseline a freshly added
  case) but refuses to cement a run that has a regression or missing case.
- The baseline is a **persisted** floor — it is never regenerated from current
  scores (that would erase the floor).

**Corpus-count floor (AC-llm.8.8, #1681/#1686)**: the per-case ratchet above
only protects a case that HAS a baseline line — if a commit removes a case's
ground-truth file **and** its `cassette-eval-baseline.jsonl` line together, the
`missing` check has nothing left to compare against and the corpus silently
shrinks. `cassette-corpus-count-baseline.json` is a **second, independent**
raise-only floor on the corpus's total case count, checked by the same
`check_cassette_graded_eval.py` gate and raised only by the same `--update`.
It cannot be bypassed by a same-commit deletion because it lives outside the
per-case JSONL entirely.

### 6.5 Coverage matrix (and its bounds)

The eval set covers a **modality × institution-class × edge-condition** matrix:

| Case (cassette) | Modality | Institution class | Edge condition |
|-----------------|----------|-------------------|----------------|
| `d69fbafc…` | text | generic | happy_path |
| `cb5dd1f7…` | text | generic | duplicate_rows (#1254) |
| `d2bef919…` | vision | named_bank | happy_path |

Minimum case count: **3** (`MIN_CASES`). Required axes asserted by
`test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count`: both modalities
(`text`, `vision`), ≥2 institution classes, and the `happy_path` +
`duplicate_rows` edge conditions.

**Drift-detection power is BOUNDED by this breadth (no overclaiming).** The gate
only detects regressions on the modality / institution-class / edge-condition
combinations present in the matrix above. **CI green is NOT a correctness
guarantee on an UNSEEN statement** — a layout, institution, or edge condition not
represented here is invisible to this gate. Live correctness on unseen documents
remains the staging `-m llm` gate's job ([§Record/Replay Cassettes](#cassettes)).
Grow the matrix by recording new cassettes + ground truth and adopting their
floors via `--update`.

### 6.6 Reliability over N samples

When a case has **N≥2** recordings (multiple cassettes of the same logical
statement), its score is the **mean** over samples (`reliability_score`),
smoothing per-run nondeterminism. **A single sample is a point estimate, NOT a
reliability measure** — one recording cannot distinguish a stable extraction from
a lucky one. To measure reliability for a case, record multiple samples; until
then a single-sample case is scored as a point estimate and documented as such.

### 6.7 Determinism & refresh

The eval is **pure Python**: no network, no API key, no DB. It runs in the CI
**lint** job alongside `check_llm_cassettes` so it never perturbs the AC
behavioural-score aggregator. Scoring is deterministic on the committed fixtures.

Refresh is a **local** operation (never CI): re-record the cassettes against a
live provider with `make llm-record`, then raise the floors:

```bash
make llm-record                                   # re-record cassettes (needs a provider key)
python tools/check_cassette_graded_eval.py --update   # raise the per-case floors
```

Commit the refreshed cassettes and the raised baseline together.

### 6.8 Real-statement corpus (source-referenced, PII-masked)

Large/scanned statements are recorded as cassettes by
`tools/_lib/record_hf_cassettes.py` (engine: GLM-4.6V, thinking disabled,
pages rendered as compressed JPEG so even scanned docs fit context). To avoid repo
bloat and PII, **the source document is never committed** — the cassette stores a
`source` reference (an HF dataset URL, or a sha256 for a local/own statement) and the
request keeps only the image content-hash, not raw bytes.

The committed response and its ground truth are PII-masked by
`tools/_lib/fixtures/extraction_pii_mask.py` (identity meta → `**`; descriptions →
`first3***last3`; flow values kept). Synthetic-source statements whose balance column
is internally inconsistent set `balance_reconciles: false` in their truth, which
exempts them from the AC23.7 balance-chain assertion while still being field-scored by
the graded eval (which pairs rows by content, not position, so a missing/re-ordered
row costs only itself).

### 6.x Own (real) statements — committed only when strict-masked to zero PII

The corpus may also include the maintainer's REAL statements (real document layouts,
multi-currency, brokerage holdings — coverage synthetic data lacks). Because git is a
zero-PII red line, a real cassette is committed ONLY after STRICT masking: identity meta
and ALL free-text (`description`, `raw_text`, `reference`, …) are fully redacted to `**`
(`mask_extraction(..., strict=True)`) — `first3***last3` is NOT enough for a real name.
Only flow values (date/amount/direction/balance/currency) and public security symbols
remain. The extraction is produced locally (no third-party API), and the cassette stores
a `sha256` source reference — never the PDF/image.

`test_AC23_8_6` enforces this structurally for every committed cassette: it is either
`synthetic: true`, or `synthetic: false` AND proven PII-free here (no CJK character
survives; every identity/free-text field is `**`). Real single-currency bank statements
that genuinely reconcile stay balance-asserted (AC23.7); brokerage and multi-currency
cassettes are balance-exempt (`balance_reconciles: false`) and field-graded only.

## 7. <a id="extraction-corpus-e2e"></a>Extraction-Corpus E2E Journeys in the Merge Tier (AC-llm.11)

> SSOT owner for the **corpus E2E tier**: the committed extraction corpus,
> seeded end-to-end through the statement pipeline in PR CI. Registered as
> roadmap group 11 in [`contract.py`](contract.py); tests live in
> `apps/backend/tests/e2e/test_statement_corpus_journeys.py` and run in the
> `ci.yml backend-e2e-tier1` merge gate.

One corpus, four consuming gates — each answers a different question:

| Gate | Stage | Question it answers |
|---|---|---|
| Cassette integrity (AC23.7, [§5](#cassettes)) | PR CI `lint` | Is each frozen extraction output internally CONSISTENT (balance chain ties)? |
| Graded field eval (AC23.8, [§6](#cassette-graded-eval)) | PR CI `lint` + `tooling-coverage` | Is each extraction output ACCURATE per field vs ground truth (raise-only floor)? |
| Extraction-unit replay (AC23.6) | PR CI backend shards (the module defaults itself to replay; text modality — the vision case is gated on re-recording, #1614) | Does the extraction service still produce this output from the frozen provider seam? |
| **Corpus E2E journeys (AC-llm.11)** | PR CI `backend-e2e-tier1` | Does each extraction output survive the full downstream pipeline — review → conflict resolution → approve → reconcile → balance sheet → income statement — with report VALUES tying to the corpus data, not just the flow completing? |

The corpus E2E tier seeds a 10-fingerprint maximally-diverse manifest
(text+vision, real bank/brokerage + synthetic HF, 0→170-transaction scales,
the #1254 duplicate-rows edge) through `seed_parsed_statement` from each
cassette's `response.stream_text` — the frozen output is the seed source
because only it carries `direction`; truth files record unsigned magnitudes.
Diversity invariants and an exact unpostable-row allowlist are asserted in
code (AC-llm.11.1) so the corpus can neither silently shrink nor silently
drop rows.

**Report-value acceptance (AC-llm.11.4/11.5, #1681/#1686)**: the balance
sheet assertion (AC-llm.11.2), the income statement assertion (AC-llm.11.4),
and the cash-flow conservation assertion (AC-llm.11.5) together are the
corpus's report-correctness proof — not just "the journey completed" but
"the numbers are right". The income statement identity holds universally
(every institution class, not a name-dependent heuristic) because
`auto_create_posted_entries_for_statement` always posts a transaction's
contra side to an Income or Expense account (a classified category or the
Income/Expense "Uncategorized" default), so `total_income − total_expenses`
equals the posting account's net movement by double-entry construction.

Cash flow is asserted differently: `generate_cash_flow` classifies "cash"
accounts by a name-keyword heuristic (`cash`/`bank`/`checking`/`savings`/…)
that brokerage-class corpus accounts (Moomoo, Futu) do not match. An earlier
version of this plan treated that as a bug to patch (make brokerage accounts
count as cash) — that would have been **wrong**: under standard cash-flow-
statement accounting, an investment account's balance change belongs in
Investing activities, not "cash". AC-llm.11.5 instead asserts
**conservation**: every corpus case's posting-account movement lands in
exactly one place — the `ending_cash` delta for cash-classified accounts, or
a single Investing/Operating/Financing line (sign-flipped per
`cash_flow_amount`'s ASSET convention) otherwise — so nothing is silently
dropped, without asserting a name-heuristic result the accounting doesn't
support.

**Division of labour with staging**: PR CI proves the pipeline on committed
extraction artifacts (zero provider spend, deterministic); the staging
provider gates prove live extraction on fixture-generated documents
(`common/testing/fixtures/pdf/generators/`). Neither substitutes for the
other.

**Corpus growth policy (right-shift finding → left-shift artifact)**: when a
staging/nightly provider gate or audit replay surfaces a failure whose cause
is deterministic (prompt assembly, schema, posting, reconciliation, report
math), the fix should land with a recorded cassette + ground truth added to
the corpus — record once, replay forever in the merge tier. Only genuine
provider drift stays right-shifted as staging/nightly evidence.
