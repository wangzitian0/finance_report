# Evidence Lineage

> **SSOT Key**: `evidence_lineage`
> **Owner EPIC**: EPIC-018
> **Purpose**: Define the generic Evidence Graph used to audit how source facts become ledger and report facts.

## Scope

Evidence lineage is a PostgreSQL-backed adjacency-list graph. It records
auditable states and the transformation processes between them.

```text
node = auditable state
edge = transformation or calculation process
```

This layer does not replace double-entry bookkeeping. Journal entries and
journal lines remain the accounting source of truth. Evidence lineage records
how source, extracted, atomic, ledger, and report entities are connected.

Evidence Graph is an audit projection. When graph rows disagree with business
tables, the owning business table wins. Graph repair must not mutate accounting
facts, report amounts, ledger balances, or legacy `JournalEntry.source_type` and
`JournalEntry.source_id` values.

## Tables

The foundation owns two generic tables:

```text
evidence_nodes
- id
- user_id
- node_kind
- entity_type
- entity_id
- properties jsonb
- created_at
- updated_at
```

```text
evidence_edges
- id
- user_id
- from_node_id
- to_node_id
- relation
- properties jsonb
- created_at
- updated_at
```

`properties` is only for small audit metadata such as confidence summaries,
algorithm names, score snapshots, or source labels. Large OCR text, PDFs, CSV
content, and provider payloads must stay in their owning business tables or
object storage.

## Node Kinds

Initial node kinds are:

- `source_document`
- `extracted_record`
- `atomic_fact`
- `review_decision`
- `ledger_entry`
- `ledger_line`
- `report_line`
- `package_snapshot`

New node kinds are allowed when a new business workflow needs a distinct
auditable state. They must be documented in the owning EPIC before use.

## Relations

Initial relation names are process-oriented:

- `parsed_into`
- `deduped_into`
- `reviewed_as`
- `posted_as`
- `contains`
- `aggregated_into`
- `included_in`
- `supports`
- `superseded_by`
- `corrected_by`

Do not use generic relations such as `related_to` for product lineage. The
relation should explain why one state can support or transform into the next.

## Identity

A node is uniquely identified by:

```text
user_id + node_kind + entity_type + entity_id
```

An edge is idempotent by:

```text
user_id + from_node_id + to_node_id + relation
```

Business tables keep their own primary keys. Evidence lineage references them
through `entity_type` and `entity_id` so future tables can join the graph
without schema changes to the graph foundation.

## Traversal

All traversal queries must:

- require `user_id`;
- support upstream direction through `to_node_id`;
- support downstream direction through `from_node_id`;
- enforce a bounded maximum depth;
- avoid loading large `properties` payloads into high-frequency UI summaries.

The default maximum traversal depth is 6. Callers may request a smaller depth.
Larger depths require a deliberate service-level override and test coverage.

## Append-Only Edges

Edges are append-oriented audit facts. Corrections should normally add
`corrected_by` or `superseded_by` edges instead of mutating historical lineage.
Foundation upsert is allowed only to keep identical writes idempotent.

## Proof

Foundation proof is owned by AC18.7 and must cover:

- node creation;
- edge creation;
- duplicate upsert behavior;
- upstream traversal;
- downstream traversal;
- depth limit enforcement;
- cross-user isolation.

Integration proof is owned by AC18.8. The first product integration path is:

```text
UploadedDocument / BankStatement
  -> BankStatementTransaction
  -> AtomicTransaction
  -> JournalEntry
  -> JournalLine
  -> report line anchor
```

The corresponding graph nodes and edges are:

```text
source_document(uploaded_document or bank_statement)
  -parsed_into->
extracted_record(bank_statement_transaction)
  -deduped_into->
atomic_fact(atomic_transaction)
  -posted_as->
ledger_entry(journal_entry)
  -contains->
ledger_line(journal_line)
  -aggregated_into->
report_line(package_traceability_line)
```

Report traceability may still use legacy `JournalEntry.source_type/source_id`
as a compatibility fallback. When a legacy source ID cannot be resolved to an
owned source, extracted, atomic, or graph node, the caller must return an
explicit blocker state rather than fabricating a source anchor.

## Navigation API and UI

Product navigation proof is owned by AC18.9. The generic lineage API resolves
one user-owned graph anchor by:

```text
entity_type + entity_id + optional node_kind
```

The API must support `upstream`, `downstream`, and `both` traversal directions
with the same bounded depth rules as the foundation service. Responses are DTOs
for UI consumption:

- `anchor`: the resolved starting node, or `null` when no owned node exists;
- `nodes`: unique graph nodes reached by the requested traversal, including the anchor when present;
- `edges`: transformation edges between returned nodes, each with relation, direction, depth, and endpoint IDs;
- `blockers`: explicit empty or unsupported states such as `graph_node_missing`;
- `max_depth`: the effective traversal depth.

UI surfaces may open lineage from report package traceability rows by using
ledger-line or source-document identifiers already returned by package
traceability. The UI must show missing lineage as an explicit empty state and
must not infer or fabricate source, ledger, or report anchors when the API does
not return graph evidence.

## Materialization and Consistency

Consistency proof for lazy materialization is owned by AC18.10. Evidence Graph
consistency is maintained through three mechanisms:

1. Transactional write-through for new facts.
2. Bounded lazy materialization for historical facts reached by lineage reads.
3. Operator dry-run detection for global drift reporting.

New source-to-ledger workflows must write graph nodes and edges inside the same
database transaction as the owning business facts. If the graph write cannot be
completed, the workflow must either fail the transaction or return an explicit
blocker. Silent graph omissions are not acceptable for new write paths.

Historical data may be materialized on demand by the lineage API. When a caller
requests an owned anchor and the expected graph anchor or local path is missing,
the API may invoke one deterministic materialization pass, then retry graph
traversal. This pass must be bounded by user scope, maximum traversal depth,
maximum graph writes, and batch size.

Lazy materialization may only use strong relationships that already exist in
source-of-truth tables, such as:

- owned uploaded document or bank statement identifiers;
- bank statement transaction to atomic transaction lineage;
- journal entry source identifiers when the source entity is owned and resolvable;
- `journal_line.journal_entry_id`;
- report traceability anchors that already reference owned ledger lines.

Lazy materialization must not infer links from fuzzy amount, date, description,
category, or account-name similarity. If provenance is ambiguous, unsupported,
missing, or cross-user, the caller must return a blocker instead of writing a
guessed edge.

Operator consistency checks are read-only by default. They report drift across
the whole graph or a user scope without modifying business tables or graph rows.
Execution-mode repair, when added, must remain deterministic, idempotent, and
limited to the same strong relationships allowed for lazy materialization.

## Blocker Taxonomy

Lineage APIs and consistency tooling must use explicit blocker codes for graph
drift and unsupported provenance:

- `graph_node_missing`: no owned graph node exists for the requested entity identity.
- `lineage_incomplete`: a graph anchor exists but the requested upstream or downstream path is incomplete.
- `orphan_graph_node`: a graph node points to a missing business entity.
- `dangling_edge`: an edge references a missing endpoint node.
- `entity_missing`: the business entity referenced by an identity cannot be resolved.
- `ambiguous_provenance`: existing facts do not identify exactly one defensible source or target.
- `unsupported_provenance`: the source type or entity type is outside the current graph contract.
- `cross_user_lineage_blocked`: a candidate link would cross user ownership boundaries.
- `materialization_write_cap_reached`: request-time repair stopped before completion because the write cap was reached.

Blockers are audit facts about missing proof. They must be surfaced instead of
fabricating source, ledger, or report anchors.
