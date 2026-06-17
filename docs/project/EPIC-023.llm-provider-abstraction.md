# EPIC-023: LLM Provider Abstraction (litellm)

> **Status**: In progress — PR1 lands the frozen contract (`src/llm/common`) and
> the secret cipher; PR2 (EPIC A) implements the litellm client/catalogue/cost
> and rewires existing call sites; PR3 (EPIC B) adds DB-backed provider config,
> the scene×model matrix, and the first-run modal.
> **Vision Anchor**: `decision-4-two-stage-review` — extraction quality depends on
> being able to pick and swap the right model per scene without code surgery.
> **Phase**: Platform / AI plumbing
> **Priority**: P1 — the AI plumbing is currently raw `httpx` against a single
> hard-coded provider; switching providers, optimising spend, or onboarding a new
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

Today the provider is reachable only by editing Python, the daily-spend guard and
fallback list are hand-rolled, provider quirks are scattered `if provider == …`
branches (OpenRouter headers, Z.AI rejecting `seed`/`response_format`), and there
is no central place that says "which model does each feature use, and what does it
cost". litellm gives us provider routing, `drop_params` (auto-dropping unsupported
fields), `reasoning_effort`, fallback/budget routing, and cost accounting for
free; this EPIC wraps it in a contract the rest of the app can depend on.

## Non-Goals

- Replacing the Z.AI `layout_parsing` private endpoint or the PyMuPDF PDF→image
  pre-processing in `extraction.py` — these stay; litellm only handles the
  OpenAI/Anthropic-shaped calls.
- A model-marketplace / multi-tenant billing system. Spend tracking stays a
  single per-deployment guard (now centralised).
- Reusing the package outside the backend (no standalone published package yet).

## Scope Slices

| Slice | PR | Owns |
|-------|----|------|
| **common** | PR1 | `src/llm/common`: value types, `ConfigSource`/`LLMClient`/`CatalogProvider`/`CostMeter` protocols, `SecretCipher`+`FernetCipher`, `docs/ssot/llm.md`. The frozen contract A and B build against. |
| **EPIC A** | PR2 | litellm `client`/`catalog`/`cost`/`routing` + `EnvConfigSource` — the litellm-backed scene surface. Cutting the legacy `ai_streaming`/`ai_models`/`extraction` call sites onto it is a deliberate follow-up (it requires migrating their transport-coupled unit tests and verifying live extraction through the post-merge AI/OCR gate). |
| **EPIC B** | PR3 | `llm_provider` + `llm_scene_binding` tables, `DbConfigSource`, `/llm/*` API, first-run modal + scene×model settings page. |

A and B depend only on **common**, not on each other, so they proceed in
parallel once PR1 merges.

## Acceptance Criteria

### AC23.1 — Frozen contract & secret encryption
> PR1 slice. The shared types/protocols and the at-rest secret cipher that EPIC A
> and EPIC B both build against.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.1.1 | The three axes are typed: `ProtocolFamily` enumerates exactly the three universal protocol families, `Scene` the fixed call sites, and `ModelSpec`/`SceneBinding` carry modality/free/reasoning so model selection is data, not code | `apps/backend/tests/unit/llm/test_types.py` | P1 |
| AC23.1.2 | `FernetCipher` round-trips a provider secret (`encrypt` → `decrypt`) and never persists plaintext | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.3 | Key rotation is single-pass: a secret sealed by an older key still decrypts after a newer key is prepended, and `rotate()` re-stamps it to the newest `key_version` | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.4 | `build_cipher()` raises `LLMConfigError` when `LLM_ENCRYPTION_KEYS` is unset, and `FernetCipher` rejects malformed keys — DB-backed secrets fail closed | `apps/backend/tests/unit/llm/test_secrets.py` | P1 |
| AC23.1.5 | The seam protocols (`ConfigSource`, `LLMClient`, `CatalogProvider`, `CostMeter`, `SecretCipher`) are runtime-checkable and a conforming implementation satisfies `isinstance`, so EPIC A/B can swap implementations behind the contract | `apps/backend/tests/unit/llm/test_contract.py` | P1 |

### AC23.2 — litellm-backed scene surface
> PR2 slice (EPIC A). The litellm implementation of the contract: provider
> routing, the scene client, the dynamic catalogue, env config, and the budget
> meter. (Legacy call-site cutover is a follow-up — see Scope Slices.)

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.2.1 | Provider routing maps each protocol family onto the correct litellm call — `openai`/`anthropic`/`openrouter` prefix, custom `api_base` for OpenAI-compatible endpoints, OpenRouter attribution headers — and normalises an already-qualified model id | `apps/backend/tests/unit/llm/test_routing.py` | P1 |
| AC23.2.2 | The litellm client streams and completes via litellm with `drop_params` (model-rejected params like `seed` are dropped, not 400'd), resolves a scene's provider/model through the `ConfigSource`, and returns text + token usage + USD cost | `apps/backend/tests/unit/llm/test_client.py` | P1 |
| AC23.2.3 | Provider failures are normalised to `LLMError` with a retryable verdict (rate-limit/5xx/timeout → retryable; others not) | `apps/backend/tests/unit/llm/test_client.py` | P1 |
| AC23.2.4 | `EnvConfigSource` projects the existing env settings onto scene bindings (vision/ocr → vision/ocr models, the rest → primary) and reports `is_configured() == False` when no API key, driving the first-run modal | `apps/backend/tests/unit/llm/test_env_config.py` | P1 |
| AC23.2.5 | The dynamic catalogue lists configured models enriched with litellm pricing, flags the free tier, and filters by provider/modality/free | `apps/backend/tests/unit/llm/test_catalog.py` | P1 |
| AC23.2.6 | The daily budget meter blocks once the USD limit is reached, rolls over per UTC day, and records spend (replacing the unenforced `AI_DAILY_LIMIT_USD`) | `apps/backend/tests/unit/llm/test_cost.py` | P1 |

### AC23.3 — DB-backed configuration & cutover
> PR3 slice (EPIC B): the provider/binding tables, the DB config source layered
> over env (all-or-nothing), and the cutover of the existing call sites onto the
> litellm client. The `/llm` API, the first-run modal, and the scene×model page
> ship in PR4 (with their own ACs) — that is where `LitellmCatalog`/`LitellmClient`
> are consumed and `services/ai_models.py` is retired.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC23.3.1 | `DbConfigSource` reads provider instances (decrypting the at-rest API key) and scene bindings (qualified by provider id) from `llm_providers` / `llm_scene_bindings` | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |
| AC23.3.2 | Config resolves DB-first with an env fallback; `is_configured()` is true when either has a provider and false when both are empty (driving the first-run modal) | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |

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
| AC23.4.1 | `GET /llm/config/status` reports `{configured}` for the current user from the layered (user → deployment → env) config source, driving the first-run modal | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.2 | `GET/POST/DELETE /llm/providers` is scoped to the current user; POST encrypts the API key via `build_cipher` before persist and the response **never** returns or logs the plaintext key; with `LLM_ENCRYPTION_KEYS` unset, POST fails closed | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.3 | `GET /llm/catalog` lists models via `LitellmCatalog` enriched with pricing/free-tier and filtered by `modality`/`free_only` | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.4 | `GET/PUT /llm/scenes` round-trips the current user's scene→model bindings (model + reasoning + fallbacks), validated against their providers | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.5 | Per-user config resolves through the scene-keyed seam: `get_config_source(user_id)` / `get_llm_client(user_id)` resolve a user's binding for a scene (qualified by provider id), falling back to the deployment default then the env model. (Threading `user_id` into the legacy `ai_streaming`/`extraction` transport call sites is the EPIC-023 follow-up noted under Scope Slices — it migrates transport-coupled tests and is verified via the post-merge AI/OCR gate.) | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.6 | The legacy `services/ai_models.py` + `routers/ai_models.py` are removed; remaining model lookups (`statements`, `chat`) resolve through `LitellmCatalog`, and the dead `AI_MODEL_CATALOG_SOURCE` config is dropped | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.7 | The daily budget meter is a process-wide singleton (`get_budget_meter`), so `get_llm_client()` reuses one accumulator and the `AI_DAILY_LIMIT_USD` ceiling is actually enforced across requests (a fresh meter per call would reset spend to zero) | `apps/backend/tests/unit/llm/test_factory.py` | P1 |
| AC23.4.8 | `DbConfigSource.get_provider` is scoped to the caller's scope (own rows, else deployment default); it never resolves or decrypts another tenant's provider by id | `apps/backend/tests/integration/test_llm_db_config.py` | P1 |
| AC23.4.9 | `api_base` rejects loopback/private/link-local/reserved IPs and local-only names (`localhost`, `*.internal`, metadata) at the schema boundary, closing the obvious SSRF foot-guns | `apps/backend/tests/integration/test_llm_api.py` | P1 |
| AC23.4.10 | Provider creation is capped per user (`MAX_PROVIDERS_PER_USER`); exceeding it returns 409 instead of growing the table unbounded | `apps/backend/tests/integration/test_llm_api.py` | P1 |
