# `advisor` — todo

The package-local worklist.  Cross-package migration lives in
[`../todo.md`](../todo.md).

## Done (PR1 — cutover)

- [x] `common/advisor/` spec surface: `contract.py` + `readme.md` + `todo.md` + `__init__.py`.
- [x] `units` declared (taxonomy-only, `module=None` — gate skips placement).
- [x] Roadmap ACs (`AC-advisor.guardrail.1/2`, `AC-advisor.session.1`,
      `AC-advisor.context.1`, `AC-advisor.cache.1`, `AC-advisor.txn.1`)
      sourced from `contract.py` (no EPIC mirror).
- [x] `advisor` entry confirmed in `common/meta/base/layering.py`
      `PACKAGE_LAYER` (layer = `"domain"`, placed ahead of this cutover).

## PR2 — closeout

- [ ] Move implementation from `src/services/ai_advisor/` →
      `src/advisor/` (`contract.implementations["be"] = "apps/backend/src/advisor"`).
- [ ] Split god-file `service.py` (~860 lines):
      - `phases/context_aggregation.py`
      - `phases/prompt_construction.py`
      - `phases/response_streaming.py`
      - `_guardrails.py` stays separate.
- [ ] Move `src/services/pii_redaction.py` → `src/advisor/_guardrails.py`
      (or merge into the guardrail module — pairs with `_guardrails`).
- [ ] Move `src/services/ai_streaming.py` → `src/advisor/extension/streaming.py`
      (zero-residue check: declared in scope additions, 2026-07-03).
- [ ] Physical `base/` / `extension/` / `data/` split:
      - `base/` — `ChatSession`, `ChatMessage`, enums, VOs, `ChatSessionRepository` port.
      - `extension/` — `AIAdvisorService`, `AdvisorGuardrails`, `ResponseCache`,
        `AdvisorSceneBinding` factory, SQL adapter.
      - `data/` — `ChatHistoryView` projection.
- [ ] Add `ARCHIVED` state to `ChatSessionStatus` + immutability invariant
      (closes `AC-advisor.session.1` to `status="done"`).
- [ ] Introduce `ChatSessionRepository` port (abstract) in `base/` +
      SQL adapter in `extension/sql.py` (replaces raw `AsyncSession`);
      set `unit.module` + `unit.impl` for the repository split.
- [ ] Fill `contract.interface` = `__init__.__all__` (after code move).
- [ ] Add structural tooling tests (`tests/tooling/test_advisor_package.py`):
      - `test_AC_advisor_1_1_only_all_is_the_published_language`
      - `test_AC_advisor_1_2_converges_by_layer`
      - `test_AC_advisor_1_3_base_layer_is_pure`
      - `test_AC_advisor_1_4_package_contract_gate_passes_for_advisor`
- [ ] Register structural tests as `invariants` in `contract.py`.
- [ ] Repoint consumers: update all `from src.services.ai_advisor.*` imports
      to `from src.advisor import …` (the package's published interface).
- [ ] Delete empty `src/services/ai_advisor/` (zero residue, single home).
- [ ] Add `portfolio` (and later `reconciliation`, `reporting`) to
      `contract.depends_on` once those packages ship their contracts
      (closes `AC-advisor.txn.1` to `status="done"`).
- [ ] `check_package_contract` green (interface == `__all__`, DAG,
      kind placement, repository split, data-sink).
