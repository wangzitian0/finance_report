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
