# EPIC-023: LLM Provider Abstraction (litellm)

> **Status**: In progress — PR1 lands the frozen contract (`src/llm/common`) and
> the secret cipher; PR2 (EPIC A) implements the litellm client/catalogue/usage
> meter and rewires existing call sites; PR3 (EPIC B) adds DB-backed provider
> config, the scene×model matrix, and the first-run modal.
> **Vision Anchor**: `decision-4-two-stage-review` — extraction quality depends on
> being able to pick and swap the right model per scene without code surgery.
> **Phase**: Platform / AI plumbing
> **Priority**: P1 — the AI plumbing is currently raw `httpx` against a single
> hard-coded provider; switching providers, tuning per-scene models, or onboarding a new
> model means editing code in several places.
> **Dependencies**: EPIC-018 (AI feature flags)

---

## Objective

Replace the bespoke `httpx` AI plumbing (`services/ai_streaming.py`,
`services/ai_models.py`, the provider calls inside `services/extraction.py`) with
**litellm behind a single in-repo package, `src/llm`**, structured around three
orthogonal axes:

```text
Axis 1  Protocol family   openai-compatible | anthropic-compatible | openrouter-compatible
Axis 2  Model             a dynamic catalogue (may be far larger than what is bound)
Axis 3  Scene             a fixed, code-defined set of call sites
Binding Scene × Model     the configurable surface (model + reasoning + fallbacks)
```

Concrete vendors are **not** special-cased: Z.AI/GLM, DeepSeek, a local vLLM, …
all slot into `openai-compatible` via a custom `api_base`. Model selection is
configuration, not code, and is intended to live in the database (EPIC B) so it
can be edited at runtime — when nothing is configured, the app prompts the user.

## Why This EPIC Exists

Today the provider is reachable only by editing Python, the fallback list is
hand-rolled, provider quirks are scattered `if provider == …` branches
(OpenRouter headers, Z.AI rejecting `seed`/`response_format`), and there is no
central place that says "which model does each feature use". litellm gives us
provider routing, `drop_params` (auto-dropping unsupported fields),
`reasoning_effort`, and fallback routing for free; this EPIC wraps it in a
contract the rest of the app can depend on. Usage is observed (request + token
counts per UTC day) rather than priced — per-token pricing and billing are too
unreliable across providers to support enforcing a money ceiling.

## Non-Goals

- Replacing the Z.AI `layout_parsing` private endpoint or the PyMuPDF PDF→image
  pre-processing in `extraction.py` — these stay; litellm only handles the
  OpenAI/Anthropic-shaped calls.
- A model-marketplace / multi-tenant billing system. Usage tracking stays a
  single per-deployment counter (request + token counts), not money/billing.
- Reusing the package outside the backend (no standalone published package yet).

## Scope Slices

| Slice | PR | Owns |
|-------|----|------|
| **common** | PR1 | `src/llm/common`: value types, `ConfigSource`/`LLMClient`/`CatalogProvider` protocols, `SecretCipher`+`FernetCipher`, `docs/ssot/llm.md`. The frozen contract A and B build against. |
| **EPIC A** | PR2 | litellm `client`/`catalog`/`usage`/`routing` + `EnvConfigSource` — the litellm-backed scene surface. Cutting the legacy `ai_streaming`/`ai_models`/`extraction` call sites onto it is a deliberate follow-up (it requires migrating their transport-coupled unit tests and verifying live extraction through the post-merge AI/OCR gate). |
| **EPIC B** | PR3 | `llm_provider` + `llm_scene_binding` tables, `DbConfigSource`, `/llm/*` API, first-run modal + scene×model settings page. |

A and B depend only on **common**, not on each other, so they proceed in
parallel once PR1 merges.

## Acceptance Criteria

### AC23.1 — Frozen contract & secret encryption
> PR1 slice. The shared types/protocols and the at-rest secret cipher that EPIC A
> and EPIC B both build against.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.1.1 | The three axes are typed: `ProtocolFamily` enumerates exactly the three universal protocol families, `Scene` the fixed call sites, and `ModelSpec`/`SceneBinding` carry modality/free/reasoning so model selection is data, not code {tier:PC} | `apps/backend/tests/unit/llm/test_types.py` | P1 |
| AC23.1.2 | `FernetCipher` round-trips a provider secret (`encrypt` → `decrypt`) and never persists plaintext {tier:PC} | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.3 | Key rotation is single-pass: a secret sealed by an older key still decrypts after a newer key is prepended, and `rotate()` re-stamps it to the newest `key_version` {tier:PC} | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.4 | `build_cipher()` raises `LLMConfigError` when `LLM_ENCRYPTION_KEYS` is unset, and `FernetCipher` rejects malformed keys — DB-backed secrets fail closed {tier:PC} | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.5 | The seam protocols (`ConfigSource`, `LLMClient`, `CatalogProvider`, `SecretCipher`) are runtime-checkable and a conforming implementation satisfies `isinstance`, so EPIC A/B can swap implementations behind the contract {tier:PC} | `apps/backend/tests/unit/llm/test_contract.py` | P1 |

### AC23.2 — litellm-backed scene surface
> PR2 slice (EPIC A). The litellm implementation of the contract: provider
> routing, the scene client, the dynamic catalogue, env config, and the usage
> meter. (Legacy call-site cutover is a follow-up — see Scope Slices.)

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.2.1 | Provider routing maps each protocol family onto the correct litellm call — `openai`/`anthropic`/`openrouter` prefix, custom `api_base` for OpenAI-compatible endpoints, OpenRouter attribution headers — and normalises an already-qualified model id {tier:PC} | `apps/backend/tests/unit/llm/test_routing.py` | P1 |
| AC23.2.2 | The litellm transport streams via litellm with `drop_params` (model-rejected params like `seed` are dropped, not 400'd) and resolves a binding's provider/model through the `ConfigSource` (`resolve_provider_and_model`, honouring the `provider_id/model` qualifier) {tier:PC} | `apps/backend/tests/unit/llm/test_client.py` | P1 |
| AC23.2.3 | Provider failures are normalised to `LLMError` with a retryable verdict (rate-limit/5xx/timeout → retryable; others not) {tier:PC} | `apps/backend/tests/unit/llm/test_client.py` | P1 |
| AC23.2.4 | `EnvConfigSource` projects the existing env settings onto scene bindings (vision/ocr → vision/ocr models, the rest → primary) and reports `is_configured() == False` when no API key, driving the first-run modal {tier:PC} | `apps/backend/tests/unit/llm/test_env_config.py` | P1 |
| AC23.2.5 | The dynamic catalogue lists configured models enriched with litellm pricing, flags the free tier, and filters by provider/modality/free {tier:PC} | `apps/backend/tests/unit/llm/test_catalog.py` | P1 |
| AC23.2.6 | The usage meter counts requests and (estimated) tokens per UTC day and rolls over at the day boundary — observability only, no money/cost and no ceiling (per-token pricing is too unreliable across providers to enforce a USD limit; the unenforced `AI_DAILY_LIMIT_USD` is dropped) {tier:PC} | `apps/backend/tests/unit/llm/test_usage.py` | P1 |

### AC23.3 — DB-backed configuration & cutover
> PR3 slice (EPIC B): the provider/binding tables, the DB config source layered
> over env (all-or-nothing), and the cutover of the existing call sites onto the
> litellm client. The `/llm` API, the first-run modal, and the scene×model page
> ship in PR4 (with their own ACs) — that is where `LitellmCatalog`/`LitellmClient`
> are consumed and `services/ai_models.py` is retired.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.3.1 | `DbConfigSource` reads provider instances (decrypting the at-rest API key) and scene bindings (qualified by provider id) from `llm_providers` / `llm_scene_bindings` {tier:PC} | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |
| AC23.3.2 | Config resolves DB-first with an env fallback; `is_configured()` is true when either has a provider and false when both are empty (driving the first-run modal) {tier:PC} | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |

### AC23.4 — `/llm` config API, per-user model selection & legacy retirement
> PR4 slice. Puts `LitellmCatalog`/`LitellmClient` on the live path behind a
> `/llm` API, makes model selection **per-user** (each user configures their own
> providers + scene→model bindings, with the deployment default as fallback and
> an OpenRouter free-tier suggestion when nothing is configured), and retires the
> legacy `services/ai_models.py` / `routers/ai_models.py` catalogue.
>
> Per-user is additive over PR3: a nullable `user_id` is added to
> `llm_providers` / `llm_scene_bindings` — `NULL` rows remain the deployment
> default (preserving AC23.3 behaviour), non-null rows are owned by that user.
> Config resolves user rows → deployment-default rows → env fallback.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.4.1 | `GET /llm/config/status` reports `{configured}` for the current user from the layered (user → deployment → env) config source, driving the first-run modal {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.2 | `GET/POST/DELETE /llm/providers` is scoped to the current user; POST encrypts the API key via `build_cipher` before persist and the response **never** returns or logs the plaintext key; with `LLM_ENCRYPTION_KEYS` unset, POST fails closed {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.3 | `GET /llm/catalog` lists models via `LitellmCatalog` enriched with pricing/free-tier and filtered by `modality`/`free_only` {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.4 | `GET/PUT /llm/scenes` round-trips the current user's scene→model bindings (model + reasoning + fallbacks), validated against their providers {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.5 | Per-user config resolves through the scene-keyed seam and is **live for the AI advisor**: `ai_streaming` resolves the provider via `get_config_source(user_id)` (the user's provider, else deployment default, else env) and `advisor.chat` prefers the user's bound model when no per-message model is given; a BYO-provider user is not blocked by a missing deployment `AI_API_KEY`. (Threading `user_id` into the remaining `extraction` OCR/vision/json call sites is the documented follow-up, verified via the post-merge AI/OCR gate.) {tier:CP} | `apps/backend/tests/integration/test_llm_api.py`, `apps/backend/tests/ai/test_ai_advisor_service.py` | P1 |
| AC23.4.6 | The legacy `services/ai_models.py` + `routers/ai_models.py` are removed; remaining model lookups (`statements`, `chat`) resolve through `LitellmCatalog`, and the dead `AI_MODEL_CATALOG_SOURCE` config is dropped {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.7 | The usage meter is a process-wide singleton (`get_usage_meter`), so the live transport accumulates onto one counter and request/token tallies survive across requests (a fresh meter per call would reset the totals); a completed live stream records one request plus estimated prompt/completion tokens, and `stream_options` is never sent (Z.AI rejects unknown params) {tier:PC} | `apps/backend/tests/unit/llm/test_factory.py`, `apps/backend/tests/ai/test_ai_streaming.py` | P1 |
| AC23.4.8 | `DbConfigSource.get_provider` is scoped to the caller's scope (own rows, else deployment default); it never resolves or decrypts another tenant's provider by id {tier:PC} | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |
| AC23.4.9 | `api_base` rejects loopback/private/link-local/reserved IPs and local-only names (`localhost`, `*.internal`, metadata) at the schema boundary, closing the obvious SSRF foot-guns {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.10 | Provider creation is capped per user (`MAX_PROVIDERS_PER_USER`); exceeding it returns 409 instead of growing the table unbounded {tier:PC} | `apps/backend/tests/integration/test_llm_api.py` | P1 |

### AC23.5 — LLM record/replay cassette layer
> Foundation slice for deterministic LLM tests in CI. A wrapper around the
> chat-completion call (`src/llm/cassette.py`, re-exported via `client.py`)
> records real provider responses locally and replays committed JSON cassettes in
> CI — no API key, no network, no flakiness. **Scope (anti-false-confidence):**
> record/replay is regression protection for KNOWN inputs only; it does NOT
> discover new real-world document shapes (that stays the staging real-doc audit
> loop), and **CI green ≠ a real unknown statement works**. Provider-specific
> correctness is the staging `-m llm` gate's job, not the cassette tests'. See
> `docs/ssot/llm.md#cassettes`. (Wiring existing extraction/advisor tests onto
> replay and the eval/drift ratchet are separate follow-up issues.)

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.5.1 | `LLM_CASSETTE_MODE` selects `replay` / `record` / `off`; it defaults to `off` (live, local dev) and an unknown value fails closed with `LLMConfigError` rather than silently calling the network {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.2 | `replay` returns the recorded response with **zero network calls and no API key** (the live call is never invoked); committed synthetic cassettes are keyed by their own fingerprint so the default store resolves them {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.3 | A request with no matching cassette is a **hard failure** in `replay` (`CassetteMiss`) that never falls back to the network, and misses batch into one actionable summary (`N cassette(s) need re-record: …; run make llm-record`) {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.4 | `record` performs the (here mocked) provider call and persists the cassette; re-recording an unchanged request is idempotent (identical bytes, no diff churn); `off` is a plain live call that writes nothing {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.5 | Fingerprint integrity: a change to an output-affecting field → different key (no stale match); two semantically-different requests → different keys (no false match); the same semantic request under a different model id → the **same** key (model-id-agnostic); image content is keyed by a bytes hash {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.6 | Normalisation strips only the intended volatile fields (timestamps, random request ids): differing volatile fields keep the key stable, while any output-relevant field changing the key proves nothing else is stripped {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |
| AC23.5.7 | A `correctness` cassette MUST refuse to record (`CassetteValidationError`) when the response fails ground-truth validation or no validator is supplied; a `flow-only` cassette records freely and never claims LLM correctness {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_cassette.py` | P1 |

### AC23.6 — Streaming-cassette bridge (the real extraction transport)
> The real extraction transport is STREAMING (`services/ai_streaming.stream_ai_json`
> → `client.litellm_stream` → `accumulate_stream`) and previously bypassed the
> AC23.5 cassette layer entirely, so PR CI never exercised the LLM path. This
> slice makes `litellm_stream` cassette-aware while **preserving streaming** for
> the caller: `off` is the prior live passthrough (prod/staging stay live & real —
> the staging `-m llm` gate is untouched), `record` accumulates the live stream
> and freezes the text, `replay` synthesises the stream from the frozen text with
> no key/network. Both text and default-config vision (OCR_MODEL==VISION_MODEL)
> flow through this path; the non-default raw-httpx layout-parser path
> (`services/extraction/_ocr.py`) is a documented out-of-scope gap. Wiring the
> first batch of extraction tests onto replay is scaffolded here (skipped pending
> real recording via `make llm-record`) so PR CI stays green; recording the real
> correctness cassettes is the operator follow-up. **Scope (anti-false-confidence):**
> as with AC23.5, CI green ≠ a real unknown statement works.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.6.1 | `litellm_stream` in `replay` serves a committed frozen-text cassette by synthesising a stream (text and image-part/vision requests both resolve their cassette) with **zero network and no API key**; the caller's `accumulate_stream` rebuilds the recorded text {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_streaming_cassette.py` | P1 |
| AC23.6.2 | A streamed request with no matching cassette is a **hard failure** in `replay` (`CassetteMiss`, scene = derived role) that never falls back to the network {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_streaming_cassette.py` | P1 |
| AC23.6.3 | `record` performs the real (here mocked) streaming call, accumulates the full text, freezes a cassette idempotently (no diff churn) and yields the text so the caller still works; a `correctness` streaming cassette refuses to record without a validator; the mode defaults to `LLM_CASSETTE_MODE` {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_streaming_cassette.py` | P1 |
| AC23.6.4 | `off` mode is an EXACT passthrough of the live (mocked) stream — deltas arrive unchanged (not collapsed), no cassette is written, and a provider failure is normalised to `LLMError` exactly as before — so prod/staging keep running the live `-m llm` path real {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_streaming_cassette.py` | P1 |
| AC23.6.5 | The fingerprint role is derived from the messages (any image part → `vision`, else `text`), so text and vision get **different** keys, while the same semantic request under a different model id resolves the **same** cassette (model-id-agnostic) {tier:PC}{proof:property} | `apps/backend/tests/unit/llm/test_streaming_cassette.py` | P1 |
| AC23.7.1 | The LLM cassette integrity gate (`tools/check_llm_cassettes.py`, lint job) fails when any committed statement-extraction cassette breaks the balance-chain invariant `opening + Σ amounts ≈ closing` (Decimal) — detectable drift for a re-recorded/inconsistent cassette; pure Python, no key/network/DB, so it never perturbs the AC behavioral-score aggregator {tier:PC}{proof:property} | `tests/tooling/test_llm_cassette_integrity.py` | P1 |
