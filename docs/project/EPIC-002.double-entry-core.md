# EPIC-002: Double-Entry Bookkeeping Core

<!-- epic-file: goal-stub -->

> **Status**: ✅ Complete — shipped and cut over to the `ledger` package.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Goal**: implement a double-entry bookkeeping system that complies with the accounting equation, supporting journal entries and account management.

All ACs, contracts, and roadmaps are owned by the `ledger` package:
[`common/ledger/contract.py`](../../common/ledger/contract.py) and [`common/ledger/readme.md`](../../common/ledger/readme.md).
This file is a goal stub kept as a product anchor; it defines no AC rows.

## Framework Boundary

The canonical ledger remains framework-neutral. Framework-specific rules (such as US GAAP or HKFRS) must not be embedded into posting logic. Account codes are canonical user ledger identifiers.
