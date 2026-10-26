# Workflow

`workflow` owns the user-facing upload-to-report lifecycle: workflow sessions,
derived event inbox entries, compact readiness state, and the next-action read
model. It composes published extraction and reporting reads; generic event bus,
outbox, HTTP, and ORM mixins remain in `platform`.

The package is an L3 domain orchestrator. Its `base` layer owns lifecycle and
response vocabulary, `extension` derives and persists workflow state, and `orm`
contains the schema-preserving `workflow_sessions` and `workflow_events` models.
`orm` also contains `workflow_sync_states`: per user, the source fingerprint and
package readiness of the last derivation. A workflow read derives again only when
the fingerprint changed (#2583, see `workflow-events.md` section 12).
