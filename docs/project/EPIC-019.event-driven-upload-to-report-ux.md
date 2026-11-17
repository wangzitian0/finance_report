# EPIC-019: Event-Driven Upload-to-Report UX

> **Status**: In Progress — core UI/API slices complete
> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-3-record-layer`, `decision-filter-accuracy-auditability`
> **Usable milestone**: G2 gating — lightweight workflow derivation feeds report readiness across uploads. Durable Prefect orchestration (`AC19.13`) stays deferred, while `DEPENDENCY_MANIFEST` still requires `workflow_engine` in staging/production (`common/runtime/sla-manifest.generated.json`).

Turns parsing, validation, reconciliation, review, and report readiness into in-app workflow events (`common/workflow/workflow-events.md`) powering upload-first landing (`/dashboard`), event inbox, and readiness cards without replacing audit logs or deterministic ledger posting.

## Framework-Aware Evidence Readiness

Report readiness must evaluate framework-specific evidence blockers from EPIC-020 — including missing settlement coverage, unresolved review, stale market data, missing valuation basis, and AI-only unreviewed policy suggestions — before marking US/HK personal reports trusted.

## Residual Acceptance Criteria

Package-owned ACs migrated to `common/{platform,reporting,extraction,meta,advisor}/contract.py` (`AC-platform.30..35.*`, `AC-reporting.readiness.*`, `AC-reporting.source-anchors.1`, `AC-extraction.1913.*`).

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.11.1 | `/review/run/{runId}` uses run-scoped Stage 2 queue and batch-approval APIs so approving a run cannot approve pending matches from another workflow session or batch. Backend half (`test_AC19_11_1_stage2_run_queue_filters_by_run_id`) migrated to the `reconciliation` package roadmap as `AC-reconciliation.run-scoped-review.1`; the frontend half stays here. | `AC19.11.1 run review uses run-scoped queue and approval endpoints` | P0 | <!-- epic-owned: fe-half -->

## References

- [common/workflow/workflow-events.md](../../common/workflow/workflow-events.md) · [common/extraction/confirmation-workflow.md](../../common/extraction/confirmation-workflow.md) · [common/reporting/readme.md](../../common/reporting/readme.md) · [apps/frontend/frontend-patterns.md](../../apps/frontend/frontend-patterns.md)
