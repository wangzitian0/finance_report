# EPIC-025: DRY/SSOT Simplification

<!-- epic-file: goal-stub -->

> **Status**: ✅ Complete — shipped and cut over to the `meta` and `reporting` packages.
> **Vision Anchor**: `decision-7-tech-stack`
> **Goal**: remove duplication across reporting calculations, workflow services, frontend contracts, and test fixtures without changing behavior.

All ACs, contracts, and roadmaps are owned by the `meta` and `reporting` packages:
[`common/meta/contract.py`](../../common/meta/contract.py) and [`common/reporting/contract.py`](../../common/reporting/contract.py).
This file is a goal stub kept as the product anchor (`apps/backend/tests/e2e/test_epic025_dry_ssot_e2e.py`); it defines no AC rows.
