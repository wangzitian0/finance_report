# EPIC-016: Two-Stage Review & Data Validation UI

> **Status**: Scope Owner
> **Vision Anchor**: `decision-4-two-stage-review`
> **Usable milestone**: G3 gating — real-data parse errors must be fixable in two-stage review.

Implements Stage 1 record review (PDF vs parsed, 0.001 USD tolerance in [confirmation-workflow.md](../../common/extraction/confirmation-workflow.md)) and Stage 2 run-level consistency review ([common/reconciliation/readme.md](../../common/reconciliation/readme.md)). Migrated `AC16.*` specs live in [common/extraction/contract.py](../../common/extraction/contract.py) and [common/reconciliation/contract.py](../../common/reconciliation/contract.py).

## Macro Proof Ownership

- `source-ledger-report-traceability`

## Horizontal & FE-Only Residue

| AC ID | Standard | Verification | Weight |
|---|---|---|---|
| AC16.1.2 | **Stage 1 UI shows PDF + parsed split view** | Manual UI test | Critical | <!-- epic-owned: fe-only -->

- [x] **AC16.11.32** Vitest harness for Stage 1 split components — shared `renderReviewComponent()` helper in `apps/frontend/src/__tests__/helpers/` <!-- epic-owned: horizontal -->
