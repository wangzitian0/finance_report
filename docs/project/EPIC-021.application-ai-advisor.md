# EPIC-021: Application-Layer AI Advisor

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Phase**: Application guidance layer
> **Priority**: P0 for upgrading AI Advisor product value from chat utility to
> contextual decision support
> **Dependencies**: EPIC-003, EPIC-005, EPIC-006, EPIC-008, EPIC-011, EPIC-013,
> EPIC-017, EPIC-018, EPIC-019, EPIC-020

---

## Objective

Define AI Advisor as a read-only application layer that consumes trusted
application state, explains what is reliable, names what is blocked, and
recommends the next in-product action.

EPIC-021 is not the source of record. It does not parse statements, classify
raw transactions, mutate ledger data, produce report snapshots, or expand source
coverage. It turns deterministic application facts into an Advisor Brief and
scoped AI explanations that help the user understand report readiness,
portfolio/cash-flow signals, data trust, and review work.

## Macro Proof Ownership

- None for PR1. EPIC-021 consumes the existing macro proof paths and will add
  product proof when Advisor Brief behavior is implemented.

## MECE Application Architecture

The Advisor product value is split into mutually exclusive lanes so application
guidance does not re-own lower-layer data, infrastructure, or processing work.

| Lane | Direction | Owner | EPIC-021 relationship |
|---|---|---|---|
| Source coverage and parsing | Evidence-to-fact | EPIC-003 / EPIC-013 | Consumes coverage and parser confidence; does not expand formats here |
| Manual evidence and asset facts | User evidence-to-fact | EPIC-011 / EPIC-005 | Consumes manual asset/liability evidence and report-line availability |
| Report package snapshots and exports | Fact-to-report | EPIC-005 / EPIC-008 | Consumes readiness, snapshot, export, and traceability status |
| Portfolio and market facts | Fact maintenance | EPIC-017 / EPIC-011 | Consumes holdings, valuation, performance, and market-data freshness |
| AI pipeline capability | Processing capability | EPIC-018 / EPIC-006 | Consumes provider, OCR, prompt, and chat foundation capabilities |
| Advisor Brief and next actions | Application guidance | EPIC-021 | Owns read-only application interpretation and user-facing next-action framing |

## Scope

Owned here:

- Application-layer advisor contract: inputs, outputs, trust boundaries, and
  next-action semantics.
- Advisor Brief product shape: readiness, trust, review, portfolio, cash-flow,
  and market freshness cards.
- Structured suggestion contract: basis, source references, confidence tier,
  limitation, and safe internal next action.
- Contextual "Ask AI about this" entry points that preserve the user's current
  report, review, portfolio, or source context.
- Safety boundary that AI can explain deterministic application facts but must
  not turn blocked, stale, unreviewed, or unsupported data into trusted
  conclusions.

Not owned here:

- Source format expansion or source confidence improvements; those stay in
  EPIC-003 / EPIC-013 and the source coverage matrix.
- report package snapshots and export scale stay in EPIC-005 / EPIC-008, tracked
  by [#705](https://github.com/wangzitian0/finance_report/issues/705).
- manual evidence intake stays in EPIC-011 / EPIC-005, tracked by
  [#706](https://github.com/wangzitian0/finance_report/issues/706).
- Framework-aware accounting policy stays in EPIC-020.
- AI provider, OCR, prompt execution, and data-processing pipeline foundations
  stay in EPIC-006 / EPIC-018.
- Trading, tax, legal, statutory filing, or regulated investment advice.

## Acceptance Criteria

### AC21.1: Product Framing and Ownership

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC21.1.1 | EPIC-021 and AI SSOT define AI Advisor as a read-only application layer that consumes deterministic application facts and is not the source of record | `test_AC21_1_1_ai_advisor_is_application_layer_contract`, `test_application_ai_advisor_epic021_product_owner_contract` | `tests/tooling/test_application_ai_advisor_epic021_contract.py`, `tests/e2e/test_application_ai_advisor_epic021.py` | P0 |
| AC21.1.2 | Scale coverage and confidence work is explicitly routed to existing EPICs and issues instead of being re-owned by EPIC-021 | `test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics`, `test_application_ai_advisor_epic021_product_owner_contract` | `tests/tooling/test_application_ai_advisor_epic021_contract.py`, `tests/e2e/test_application_ai_advisor_epic021.py` | P0 |

### AC21.2: Backend Advisor Context and Suggestions

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC21.2.1 | Backend advisor context includes deterministic report readiness, source trust, workflow action counts, market-data freshness, portfolio facts, cash-flow facts, and structured source-cited suggestions | `test_AC21_2_1_advisor_context_includes_readiness_trust_workflow_and_suggestions` | `apps/backend/tests/ai/test_ai_advisor_service.py` | P0 |
| AC21.2.2 | Prompt construction consumes structured advisor facts and must not describe blocked, stale, unreviewed, unsupported, or manual-trusted data as trusted | `test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state` | `apps/backend/tests/ai/test_ai_advisor_service.py` | P0 |
| AC21.2.3 | Chat provider calls and persisted chat messages redact sensitive numeric fields while preserving read-only advisor behavior | `test_AC21_2_3_chat_stream_redacts_sensitive_numbers_before_provider_and_persistence` | `apps/backend/tests/ai/test_ai_advisor_service.py` | P0 |

## Planned Implementation Slices

These are issue-scoped follow-ups. They should add their own AC IDs only when
their tests are introduced.

1. PR1 - Product/SSOT framing: create EPIC-021, update AI SSOT, register the
   initial ownership ACs, and wire project indexes.
2. PR2 - Backend advisor context: expose deterministic advisor facts for
   readiness, source trust, workflow blockers, pending review, market freshness,
   portfolio, and cash-flow state. This slice owns AC21.2.1 through AC21.2.3.
3. PR3 - Frontend Advisor Brief: render structured cards, safe next-action
   routes, and contextual chat entry points.

## Tracking Issues

- PR1 framing: [#711](https://github.com/wangzitian0/finance_report/issues/711)
- PR2 backend context and suggestion engine:
  [#712](https://github.com/wangzitian0/finance_report/issues/712)
- PR3 frontend Advisor Brief and contextual UX:
  [#713](https://github.com/wangzitian0/finance_report/issues/713)

## Related

- [ai.md](../ssot/ai.md)
- [reporting.md](../ssot/reporting.md)
- [workflow-events.md](../ssot/workflow-events.md)
- [source-coverage-matrix.yaml](../ssot/source-coverage-matrix.yaml)
- [EPIC-006](./EPIC-006.ai-advisor.md)
- [EPIC-018](./EPIC-018.ai-driven-pipeline.md)
- [EPIC-019](./EPIC-019.event-driven-upload-to-report-ux.md)
- [EPIC-020](./EPIC-020.framework-aware-personal-reporting.md)
