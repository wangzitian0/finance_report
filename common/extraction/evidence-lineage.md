# Evidence Lineage

> **SSOT Key**: `evidence_lineage` | PostgreSQL audit projection (`evidence_nodes`, `evidence_edges`) tracing source documents to ledger and report anchors. Business tables remain authoritative on conflict.

## Graph Model & Identity

```text
node = auditable state
edge = transformation or calculation process
```

- **Node identity**: `user_id + node_kind + entity_type + entity_id` (`node_kind`: `source_document`, `extracted_record`, `atomic_fact`, `review_decision`, `ledger_entry`, `ledger_line`, `report_line`, `package_snapshot`).
- **Edge identity**: `user_id + from_node_id + to_node_id + relation` (`parsed_into`, `deduped_into`, `reviewed_as`, `posted_as`, `contains`, `aggregated_into`, `included_in`, `supports`, `superseded_by`, `corrected_by`). Tenant-scoped composite FKs forbid cross-user edges.

## Traversal, Opening Positions & Blockers

- Traversal requires `user_id` across `upstream`/`downstream`/`both`. `The default maximum traversal depth is 6`.
- `opening_position` resolves via `current_authoritative` source/stock decisions (`opening_authority_unproven` -> HTTP 409 on revoked/superseded anchors).
- New workflows write graph rows in the same DB transaction; bounded lazy materialization repairs historical anchors strictly from relational link tables (`atomic_transaction_source_documents`, `atomic_position_source_documents`, `reconciliation_match_journal_entries`), returning explicit blocker codes (`graph_node_missing`, `lineage_incomplete`, `entity_missing`, `ambiguous_provenance`, `unsupported_provenance`, `cross_user_lineage_blocked`, `materialization_write_cap_reached`).
