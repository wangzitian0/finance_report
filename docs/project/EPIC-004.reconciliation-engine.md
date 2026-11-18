# EPIC-004: Reconciliation Engine & Matching

> **Status**: Complete (TDD Aligned)
> **Vision Anchor**: `decision-4-two-stage-review`

Matches bank transactions with journal entries (auto-accept `>= 85`, review queue `60-84`, unmatched `< 60`). See [common/reconciliation/readme.md](../../common/reconciliation/readme.md) and [common/meta/schema.md](../../common/meta/schema.md).

## Notes & Debt

- 100-transaction manual false-positive audit and 10,000-transaction benchmark evidence run in `apps/backend/tests/reconciliation/test_reconciliation_audit.py` and fail CI if targets miss.
- Owned user/reference docs: [reconciliation.md](../user-guide/reconciliation.md), [api.md](../reference/api.md).
