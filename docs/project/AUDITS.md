# Audit Index
This file indexes project consistency and traceability audits. Use generated reports for current metrics.
## Current Generated Evidence
| Source | Purpose |
|---|---|
| `python -m common.testing.preflight --tier=static` | Pre-push structural, lint, OpenAPI, and boundary verification |
| [traceability-exceptions.md](traceability-exceptions.md) | Classified helper/SSOT tests that serve as shared test infrastructure |
Live verification runs through `check_app_boundary.py`, `check_base_purity.py`, `check_tier_imports.py`, and CI unit/E2E suites (`common/meta/flows/user_cases_ssot.json`).
## Historical Audits
| Report | Date | Scope | Status |
|---|---|---|---|
| [Issue #548](https://github.com/wangzitian0/finance_report/issues/548) | 2026-02 era | Removed archive inventory | Retention index only; active truth lives in EPICs, README, registries, generated reports, and CI artifacts |
## Audit Rules
1. Current counts should come from generated tooling, not hand-maintained prose. 2. New project audits should explain what was checked and link to generated evidence. 3. When an audit finds work that belongs in code or tests, create an issue and reference it instead of encoding future behavior in prose.
## Retired Standalone Reports
The root `TESTING_GAP_ANALYSIS.md` report was retired during the 2026-05-20 documentation cleanup. Its old hand-written testing narrative duplicated `common/testing/tdd.md`, `common/testing/coverage.md`, `common/testing/ci-cd.md`, and the AC tooling and CI artifacts. Current testing gaps are tracked by issues [#454](https://github.com/wangzitian0/finance_report/issues/454) and
[#456](https://github.com/wangzitian0/finance_report/issues/456). `docs/project/archive/**` was swept on 2026-05-20, then removed from the repository after the retained inventory was indexed in [#548](https://github.com/wangzitian0/finance_report/issues/548). Useful archive content is now owned by active EPICs and generated reports: | Archive Source | Current Owner |
|---|---|
| `EPIC-002-*` | EPIC-002 integration notes | | `EPIC-004.reconciliation-accuracy-report.md` | EPIC-004 issues and integration notes | | `EPIC-ENCODING-SUMMARY.md` | EPIC-011, EPIC-012, EPIC-013, EPIC-014 | | `EPIC-QA-Standardization.md`, `QA_REPORT_20260121.md` | EPIC-012 and EPIC-014 |
| `TEST-COVERAGE-PLAN.md`, `testing-gap-analysis.md`, `testing-implementation.md` | EPIC-008, AC tooling, and CI artifacts |
| AC audit archives | This audit index and EPIC-014 |
Related cleanup issues: - [#453](https://github.com/wangzitian0/finance_report/issues/453) - [#454](https://github.com/wangzitian0/finance_report/issues/454) - [#455](https://github.com/wangzitian0/finance_report/issues/455) - [#456](https://github.com/wangzitian0/finance_report/issues/456)
