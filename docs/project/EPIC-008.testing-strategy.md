# EPIC-008: Comprehensive Testing Strategy (Smoke & E2E)

> **Status**: Core Complete
> **Vision Anchor**: `decision-filter-accuracy-auditability`

Defines end-to-end smoke, Tier-1..3 E2E, and CI test execution strategy. Authoritative AC definitions live in [common/testing/contract.py](../../common/testing/contract.py), [common/testing/ci-cd.md](../../common/testing/ci-cd.md), and [common/testing/readme.md](../../common/testing/readme.md).

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `monthly-income-spending`
- `investment-performance`
- `source-ledger-report-traceability`

## Horizontal Residual Ownership

| ID | Test Case | Test Function | File | Priority |
|---|---|---|---|---|
| AC8.13.61 | Visual regression residual is explicitly owned by EPIC-008 as a P3 future testing capability | `test_AC8_13_61_visual_regression_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P3 | <!-- epic-owned: horizontal -->
| AC8.13.62 | Test observability residuals are explicitly owned by EPIC-008 with current replacements and future test report dashboard, failure notification, and trend analysis scope | `test_AC8_13_62_test_observability_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 | <!-- epic-owned: horizontal -->
| AC8.13.63 | Performance testing residual is explicitly owned by EPIC-008 with current Locust/staging coverage and future P95 trend gate scope | `test_AC8_13_63_performance_testing_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 | <!-- epic-owned: horizontal -->
