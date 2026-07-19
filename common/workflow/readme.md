# Workflow

`workflow` owns the user-facing upload-to-report lifecycle: workflow sessions,
derived event inbox entries, compact readiness state, and the next-action read
model. It composes published extraction and reporting reads; generic event bus,
outbox, HTTP, and ORM mixins remain in `platform`.

The package is an L3 domain orchestrator. Its `base` layer owns lifecycle and
response vocabulary, `extension` derives and persists workflow state, and `orm`
contains the schema-preserving `workflow_sessions` and `workflow_events` models.

## Bounded-context decision

`workflow` owns the cross-context process state a user sees: sessions, derived
event inbox entries, readiness, and next actions. It consumes extraction,
reconciliation, and reporting projections; it does not own their source facts,
matches, or report documents. `platform` supplies persistence composition only,
not workflow policy. The machine-readable boundary and relationships are in
[`contract.py`](./contract.py).
