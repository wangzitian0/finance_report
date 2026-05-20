# Testing Gap Analysis

> Historical note: this file used to contain a hand-written test coverage and
> E2E strategy report. It is no longer the source of truth for testing status.

Current testing truth is split as follows:

- Project proof summary: [README.md](./README.md)
- AC-to-test coverage report:
  [docs/analysis/test-ac-coverage-report.md](./docs/analysis/test-ac-coverage-report.md)
- TDD workflow: [docs/ssot/tdd.md](./docs/ssot/tdd.md)
- Coverage policy: [docs/ssot/coverage.md](./docs/ssot/coverage.md)
- CI/test strategy: [docs/ssot/ci-cd.md](./docs/ssot/ci-cd.md)

The stale hand-written unit-test narrative was removed because current coverage
is code-owned by `scripts/coverage_policy.py`, `unified-coverage.json`, and CI
coverage reports.

Testing gaps discovered during the 2026-05-20 documentation cleanup are tracked
as issues instead of prose plans:

- [#452](https://github.com/wangzitian0/finance_report/issues/452): harden AC
  traceability against stub and placeholder tests.
- [#454](https://github.com/wangzitian0/finance_report/issues/454): convert
  manual-verification ACs into automated tests or explicit manual gates.
- [#456](https://github.com/wangzitian0/finance_report/issues/456): fix
  AC-to-EPIC mismatch and invalid test references.
