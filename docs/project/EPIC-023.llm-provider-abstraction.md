# EPIC-023: LLM Provider Abstraction (litellm)

> **Status**: ✅ Complete — shipped across EPIC A/B and cut over to the `llm` package (#1426); the frozen contract (`src/llm/base`, formerly `src/llm/common`) and
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
`services/ai_models.py`, the provider calls inside the extraction pipeline) with
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
| **common** | PR1 | `src/llm/base` (was `src/llm/common`): value types, `ConfigSource`/`LLMClient`/`CatalogProvider` protocols, `SecretCipher`+`FernetCipher`, [`common/llm/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/llm/readme.md) (the LLM SSOT, internalized into the `llm` package). The frozen contract A and B build against. |
| **EPIC A** | PR2 | litellm `client`/`catalog`/`usage`/`routing` + `EnvConfigSource` — the litellm-backed scene surface. Cutting the legacy `ai_streaming`/`ai_models`/`extraction` call sites onto it is a deliberate follow-up (it requires migrating their transport-coupled unit tests and verifying live extraction through the post-merge AI/OCR gate). |
| **EPIC B** | PR3 | `llm_provider` + `llm_scene_binding` tables, `DbConfigSource`, `/llm/*` API, first-run modal + scene×model settings page. |

A and B depend only on **common**, not on each other, so they proceed in
parallel once PR1 merges.

## Acceptance Criteria

> **Migrated (2026-07-03, #1426 Stage-2 cutover):** all 44 ACs moved to the
> `llm` package roadmap in [`common/llm/contract.py`](../../common/llm/contract.py)
> as `AC-llm.<group>.<seq>` (numeric grammar, leading epic number dropped:
> the leading `23` is dropped, group and sequence preserved), per Decision A (standard-preserving move — every
> AC kept its statement, anchored test, and priority; the package tier is
> LLM-LED with per-AC `proof_kind`). This table intentionally holds no rows;
> the contract roadmap is the single source.
>
> Cassette fixture *data* (the 32-case corpus + graded-eval baseline) lives in
> the `testing` package (#1553, `AC-testing.*`); the cassette *mechanism* ACs
> above are llm's (`common/testing/contract.py` documents the split).
>
> Migrated ids (each resolves in the contract roadmap):
>
> `AC-llm.1.1`
> `AC-llm.1.2`
> `AC-llm.1.3`
> `AC-llm.1.4`
> `AC-llm.1.5`
> `AC-llm.2.1`
> `AC-llm.2.2`
> `AC-llm.2.3`
> `AC-llm.2.4`
> `AC-llm.2.5`
> `AC-llm.2.6`
> `AC-llm.3.1`
> `AC-llm.3.2`
> `AC-llm.4.1`
> `AC-llm.4.2`
> `AC-llm.4.3`
> `AC-llm.4.4`
> `AC-llm.4.5`
> `AC-llm.4.6`
> `AC-llm.4.7`
> `AC-llm.4.8`
> `AC-llm.4.9`
> `AC-llm.4.10`
> `AC-llm.5.1`
> `AC-llm.5.2`
> `AC-llm.5.3`
> `AC-llm.5.4`
> `AC-llm.5.5`
> `AC-llm.5.6`
> `AC-llm.5.7`
> `AC-llm.6.1`
> `AC-llm.6.2`
> `AC-llm.6.3`
> `AC-llm.6.4`
> `AC-llm.6.5`
> `AC-llm.7.1`
> `AC-llm.8.1`
> `AC-llm.8.2`
> `AC-llm.8.3`
> `AC-llm.8.4`
> `AC-llm.8.5`
> `AC-llm.8.6`
> `AC-llm.8.7`
> `AC-llm.9.1`
