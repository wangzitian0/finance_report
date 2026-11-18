# EPIC-019: Event-Driven Upload-to-Report UX

> **Status**: In Progress — core UI/API slices complete
> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-3-record-layer`, `decision-filter-accuracy-auditability`
> **Usable milestone**: G2 gating — lightweight workflow derivation feeds report readiness across uploads. Durable Prefect orchestration (`AC19.13`) stays deferred, while `DEPENDENCY_MANIFEST` still requires `workflow_engine` in staging/production.

Turns parsing, validation, reconciliation, review, and report readiness into in-app workflow events (`common/workflow/workflow-events.md`) powering upload-first landing (`/dashboard`), event inbox, and readiness cards without replacing audit logs or deterministic ledger posting.

## Framework-Aware Evidence Readiness

Report readiness must evaluate framework-specific evidence blockers from EPIC-020 — including missing settlement coverage, unresolved review, stale market data, missing valuation basis, and AI-only unreviewed policy suggestions — before marking US/HK personal reports trusted.

## References

- [common/workflow/workflow-events.md](../../common/workflow/workflow-events.md) · [common/extraction/confirmation-workflow.md](../../common/extraction/confirmation-workflow.md) · [common/reporting/readme.md](../../common/reporting/readme.md) · [apps/frontend/frontend-patterns.md](../../apps/frontend/frontend-patterns.md)
