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
| **EPIC A** | PR2 | litellm `client`/`catalog`/`cost` implementations + `EnvConfigSource`; rewire `ai_streaming`/`ai_models`/`extraction` to delegate. |
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
