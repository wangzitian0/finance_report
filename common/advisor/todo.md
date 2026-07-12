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

## Done (PR2 — physical move, #1671 Wave B)

- [x] Move implementation from `src/services/ai_advisor/` →
      `src/advisor/` (`contract.implementations["be"] = "apps/backend/src/advisor"`).
- [x] Physical `base/` / `extension/` layering:
      - `base/` — `prompt.py` (absorbed `src/prompts/ai_advisor.py`),
        `constants.py`, `guardrails.py` (pure).
      - `extension/` — `service.py`, `cache.py`, `app_reads.py` (ports),
        `annualized_income.py` (absorbed `src/services/annualized_income.py`).
      - `orm/` — `chat.py` (absorbed `src/models/chat.py`, schema-neutral;
        Alembic diff empty; `models/_registry.py` imports the package root).
- [x] ~~Move `src/services/pii_redaction.py` → `src/advisor/_guardrails.py`~~
      Superseded by #1677's ruling: `pii_redaction` moved to
      `src/observability/pii_redaction.py` — its consumers are observability's
      audit helpers and extraction's CSV path, not the advisor. Advisor's
      `base/guardrails.py` keeps its own chat-stream redaction (a separate concern).
- [x] ~~Move `src/services/ai_streaming.py` → `src/advisor/extension/streaming.py`~~
      Superseded by #1670's ruling: `ai_streaming` moved to
      `src/llm/extension/streaming.py` (#1748) — it is the shared litellm
      streaming transport for three domains (extraction, reconciliation,
      advisor's chat), not advisor-private glue; the advisor imports
      `stream_ai_chat` from the `llm` published root.
- [x] Fill `contract.interface` = `__init__.__all__` (28 published names).
- [x] Declare the real `depends_on` edges (honesty gate both ways):
      `audit`, `llm`, `observability`, `platform`, `portfolio`, `pricing`,
      `reconciliation` — all real imports through published roots; DAG acyclic.
      `config` dropped (folded into runtime, #1669 — `src.config` is bare
      shared infra); `reporting` deliberately absent — consumed through the
      `extension/app_reads.py` ports until the #1666 fold lands.
- [x] Remainder reads inverted through `extension/app_reads.py` ports wired
      by the composition root (`src/main.py`), #1676 idiom: reporting trio +
      `ReportError`, report readiness, `observed_fx_pairs`, windowed
      `convert_amount` + `FxRateError`, `income_bucket`.
- [x] Repoint consumers: `routers/chat.py`, `routers/reports.py`, tests →
      `from src.advisor import …` (the package's published interface).
- [x] Delete `src/services/ai_advisor/`, `src/services/annualized_income.py`,
      `src/prompts/`, `src/models/chat.py` (zero residue, single home).
- [x] Structural tooling tests (`tests/tooling/test_advisor_package.py`):
      impl-at-contracted-path, no-remainder-imports, package-gate-green
      (closes `AC-advisor.txn.1` to `status="done"`).
- [x] Bounded-context proof (`tests/ai/test_advisor_bounded_context.py`):
      context == exactly the bounded read set, citations restricted to
      bounded sources + safe hrefs (re-anchors `AC-advisor.context.1`).
- [x] `check_package_contract` green (interface == `__all__`, DAG both-ways
      honesty, one-txn import/FK edges); `check_app_boundary` green (no new
      edges — baseline unchanged at 5).

## Follow-ups (open)

- [ ] Collapse `extension/app_reads.py` ports into direct published-root
      imports + `depends_on` edges when the owners physically fold:
      reporting/report_readiness/reporting_calc (#1666), fx conversion +
      the fx-pair composer (#1610).
- [ ] Split god-file `extension/service.py` (~860 lines):
      - `phases/context_aggregation.py`
      - `phases/prompt_construction.py`
      - `phases/response_streaming.py`
      - `base/guardrails.py` stays separate.
- [ ] Add `ARCHIVED` state to `ChatSessionStatus` + immutability invariant
      (closes `AC-advisor.session.1` to `status="done"`).
- [ ] Introduce `ChatSessionRepository` port (abstract) in `base/` +
      SQL adapter in `extension/sql.py` (replaces raw `AsyncSession`);
      set `unit.module` + `unit.impl` for the repository split.
- [ ] Set `unit.module` paths for the placed units (guardrails, cache,
      service) once the phase split settles; register structural tests as
      `invariants` in `contract.py`.
- [ ] `data/` layer: materialize the `ChatHistoryView` projection (the
      chat-history query currently lives in `routers/chat.py`).
