# EPIC-026: AC Authority Tiers

> **Status**: In Progress
> **Vision Anchor**: `decision-7-tech-stack`

Binds every AC to one authority tier (`CODE-ONLY / CODE-LED / HU / LLM-LED / LLM-ONLY`) so test proof shape matches decision authority. Vocabulary and proof matrix live in [common/meta/readme.md](../../common/meta/readme.md); system ACs live in [common/meta/contract.py](../../common/meta/contract.py) and [common/observability/contract.py](../../common/observability/contract.py).

## Horizontal Residue

| ID | Requirement | Test Function | File | Priority |
|---|---|---|---|---|
| AC26.9.1 | A base library classifies every AC as `CODE` or `LLM` **detected from its test shape** (a record/replay cassette test -> `LLM`; a structured-input deterministic test -> `CODE`), and a counter aggregates each package into an `LLM-share` mapped to one of four bands — `CODE-ONLY` (`s = 0`), `CODE-LED` (`0 < s < 50`), `LLM-LED` (`50 <= s < 100`), `LLM-ONLY` (`s = 100`). Classification is detected, never declared, so the band is computed not argued. See `common/meta/readme.md` §CODE/LLM bit. {tier:CODE-ONLY} {proof:property} | `test_AC26_9_1_band_boundaries`, `test_AC26_9_1_test_shape_classifies_code_vs_llm` | `tests/tooling/test_authority_classifier.py` | P0 | <!-- epic-owned: horizontal -->
