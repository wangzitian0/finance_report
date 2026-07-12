# EPIC-023: LLM Provider Abstraction (litellm)

<!-- epic-file: goal-stub -->

> **Status**: ✅ Complete — shipped and cut over to the `llm` package (#1426).
> **Vision Anchor**: `decision-4-two-stage-review`
> **Goal**: replace the bespoke `httpx` AI plumbing with litellm behind one
> in-repo package, structured as three orthogonal axes — protocol family ×
> model catalogue × scene — with the scene×model binding as the only
> configurable surface.

All 44 ACs, the axes/rotation vocabulary, and the cassette mechanism are owned
by the `llm` package: [`common/llm/contract.py`](../../common/llm/contract.py)
(roadmap, `AC-llm.*`) and [`common/llm/readme.md`](../../common/llm/readme.md).
This file is a goal stub kept as the product E2E anchor
(`tests/e2e/test_llm_provider_abstraction_epic023.py`); it defines no AC rows.
