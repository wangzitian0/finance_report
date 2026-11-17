# Confirmation Workflow — Parse-Confirm (Stage 1)

> **SSOT Key**: `confirmation-workflow` (parse-confirm half) | Stage 2 half: [common/reconciliation/confirmation-workflow.md](../reconciliation/confirmation-workflow.md#state-machine).

## Status Fields & Tolerance

`StatementSummary.stage1_status` (`PENDING_REVIEW`, nullable after upload) is Stage 1 statement review; `ReconciliationMatch.status` (`PENDING_REVIEW`) is Stage 2 match review. They are independent state machines.

| Context | Tolerance | Source |
|---|---|---|
| Stage 1 balance-chain validation | `0.001 USD` | `src.audit.promotion.STATEMENT_BALANCE_TOLERANCE` |
| Cross-period statement gap plug (`3198`) | `0.10 USD` | `src.ledger.account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE` |
| Stage 2 auto-accept / review | `85 / 60` | `src.audit.promotion.RECONCILIATION_{AUTO_ACCEPT,REVIEW}_SCORE` |

## <a id="state-machine"></a>State Machine & Rules

```text
Stage 1: upload -> parsed -> (score >= 85 + 0.001 USD + account + non-overlapping period -> approved)
                          -> (pending_review -> approve_statement -> approved | reject_statement -> rejected -> re-parse)
Stage 2: reconciliation_match -> (>= 85 auto_accepted | 60..84 pending_review -> accepted/rejected | < 60 unmatched)
```

- Always scope mutations by `user_id`. Reject + re-parse instead of in-place editing (no edit-and-approve endpoint exists).
- Block Stage 1 approval on `> 0.001 USD` balance-chain error or unresolved duplicate/transfer-pair candidates.
- Render Stage 1 rows with LOW rows on top, unrated rows marked `Not rated`, wrapped descriptions, and source preview only for PDF/PNG/JPG (`GET /api/statements/pending-review`, `POST /api/statements/{id}/review/{approve,reject}`).

### <a id="confidence-tier-rollup"></a>Confidence Tier Rollup & Promotion Gate

Confidence ranks `TRUSTED > HIGH > MEDIUM > LOW`. Aggregates take the minimum tier of contributing rated facts (excluding unrated adjustments; `null` if none rated). `src.audit.promotion` enforces `authoritative <=> invariants_pass and confidence >= tau`; `extraction/extension/correction_loop.py` feeds user overrides into `CorrectionLog`.

Related: [common/extraction/readme.md](./readme.md) · [common/audit/readme.md](../audit/readme.md#source-type-trust-hierarchy-provenance) · [common/meta/schema.md](../meta/schema.md)
