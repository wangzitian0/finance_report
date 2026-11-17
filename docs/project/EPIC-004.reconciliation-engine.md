# EPIC-004: Reconciliation Engine & Matching

> **Status**: Complete (TDD Aligned)
> **Vision Anchor**: `decision-4-two-stage-review`

Matches bank transactions with journal entries (auto-accept `>= 85`, review queue `60-84`, unmatched `< 60`). See [common/reconciliation/readme.md](../../common/reconciliation/readme.md), [common/reconciliation/contract.py](../../common/reconciliation/contract.py), and [common/meta/schema.md](../../common/meta/schema.md).

## Horizontal Residue & Benchmark Ownership

| ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC4.8.1 | Archive baseline benchmark residual is explicitly owned by EPIC-004 until synthetic accuracy and performance proof exists | `test_AC4_8_1_reconciliation_benchmark_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P1 | <!-- epic-owned: horizontal -->
| AC4.10.3 | The reconciliation audit thresholds (accuracy, false-positive, false-negative, 10,000-transaction runtime) are enforced by the backend reconciliation test suite; the standalone CI job and its `tools/reconciliation_audit.py` shim are retired (#2934 Wave A) | `test_reconciliation_audit` | `apps/backend/tests/reconciliation/test_reconciliation_audit.py` | P0 | <!-- epic-owned: horizontal -->

## Notes & Debt

- **0.1 USD Threshold** (`AC4.6.1 removed` -> `AC-reconciliation.source-type-transfer.1`, #1663).
- Archive baseline benchmark residual is explicitly owned by EPIC-004 and now closed through AC4.10.3: 100-transaction manual false-positive audit + 10,000-transaction benchmark evidence runs in `apps/backend/tests/reconciliation/test_reconciliation_audit.py` and fails CI if targets miss.
- AC graph consistency is gated by `python tools/check_ac_index.py`.
- Owned user/reference docs: [reconciliation.md](../user-guide/reconciliation.md), [api.md](../reference/api.md).
