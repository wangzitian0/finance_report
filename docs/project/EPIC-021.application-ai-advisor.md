# EPIC-021: Application-Layer AI Advisor

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Phase**: Application guidance layer
> **Priority**: P0 for upgrading AI Advisor product value from chat utility to
> contextual decision support
> **Dependencies**: EPIC-003, EPIC-005, EPIC-006, EPIC-008, EPIC-011, EPIC-013,
> EPIC-017, EPIC-018, EPIC-019, EPIC-020
> **Usable milestone**: ⏸️ deferred (post-Usable). The application-layer advisor is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1); trusting the report numbers does not depend on advisor depth.

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
| AC21.1.1 | EPIC-021 and AI SSOT define AI Advisor as a read-only application layer that consumes deterministic application facts and is not the source of record {tier:CODE-ONLY} | `test_AC21_1_1_ai_advisor_is_application_layer_contract`, `test_application_ai_advisor_epic021_product_owner_contract` | `tests/tooling/test_application_ai_advisor_epic021_contract.py`, `tests/e2e/test_application_ai_advisor_epic021.py` | P0 |
| AC21.1.2 | Scale coverage and confidence work is explicitly routed to existing EPICs and issues instead of being re-owned by EPIC-021 {tier:CODE-ONLY} | `test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics`, `test_application_ai_advisor_epic021_product_owner_contract` | `tests/tooling/test_application_ai_advisor_epic021_contract.py`, `tests/e2e/test_application_ai_advisor_epic021.py` | P0 |

### AC21.2: Backend Advisor Context and Suggestions

> *(This group's first row removed — duplicate of the already-migrated `AC-advisor.context.1`, same test function. Its third row removed too — duplicate of `AC-advisor.guardrail.2`.)* The middle row migrated to
> [`common/advisor/contract.py`](../../common/advisor/contract.py)'s `roadmap` (migration closeout wave 2, #1663): `AC-advisor.context.4`.

### AC21.3: Frontend Advisor Brief and Contextual Next Actions

> *(This group's first row removed — migrated to [`common/advisor/contract.py`](../../common/advisor/contract.py)'s `roadmap` as `AC-advisor.suggestions.3`, migration closeout wave 2, #1663.)* The remaining three rows stay here: they are frontend/E2E tests (`.tsx`/`.spec.ts`), and the governance gate's `_resolve_test()` (AST-based, Python-only) cannot resolve a non-Python test path — same limitation as EPIC-012's `AC12.27.3`/`AC12.28.3`.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC21.3.2 | Advisor Brief renders blocked, ready, review-required, and stale-market-data cards with source basis, limitation, and safe internal action links {tier:CODE-ONLY} | `test_AC21_3_2_advisor_brief_renders_structured_cards_and_safe_routes` | `apps/frontend/src/__tests__/advisorBrief.test.tsx` | P0 |
| AC21.3.3 | Chat and dashboard surfaces expose contextual Ask AI links that seed a scoped prompt without losing existing chat behavior {tier:CODE-ONLY} | `test_AC21_3_3_chat_panel_renders_contextual_advisor_brief`, `test_AC21_3_3_dashboard_renders_advisor_brief_before_analytics` | `apps/frontend/src/__tests__/chatPanelComponent.test.tsx`, `apps/frontend/src/__tests__/dashboardPage.test.tsx` | P0 |
| AC21.3.4 | Advisor Brief keeps desktop and mobile layouts free of horizontal overflow {tier:CODE-ONLY} | `advisor-brief desktop and mobile layouts avoid horizontal overflow` | `apps/frontend/playwright/advisor-brief.spec.ts` | P1 |

## Planned Implementation Slices

These are issue-scoped follow-ups. They should add their own AC IDs only when
their tests are introduced.

1. PR1 - Product/SSOT framing: create EPIC-021, update AI SSOT, register the
   initial ownership ACs, and wire project indexes.
2. PR2 - Backend advisor context: expose deterministic advisor facts for
   readiness, source trust, workflow blockers, pending review, market freshness,
   portfolio, and cash-flow state. This slice owns the AC21.2.* group (mostly
   migrated to the advisor package roadmap since, #1663 — see AC21.2 above).
3. PR3 - Frontend Advisor Brief: render structured cards, safe next-action
   routes, and contextual chat entry points. This slice owns the AC21.3.*
   group (partially migrated since, #1663 — see AC21.3 above).

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
