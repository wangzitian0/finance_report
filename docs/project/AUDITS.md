# Audit Index

This file indexes project consistency and traceability audits. Use generated
reports for current metrics.

## Current Generated Reports

| Report | Purpose |
|---|---|
| [../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md) | Current AC-to-test coverage, stub-only ACs, untested ACs, invalid AC references |
| [../analysis/ac-epic-mismatch-report.md](../analysis/ac-epic-mismatch-report.md) | Current AC-to-EPIC mismatch triage, separated into actionable and fixture-only refs |
| [../analysis/traceability-exceptions.md](../analysis/traceability-exceptions.md) | Classified helper/SSOT tests and source surfaces that are not AC proof |

Current generated AC snapshot values are owned by:

- `docs/analysis/test-ac-coverage-report.md`
- `docs/analysis/ac-epic-mismatch-report.md`
- `python scripts/analyze_test_ac_coverage.py --stdout`
- `python scripts/check_ac_traceability.py`

Placeholder assertion, pure-pass, pure-skip, and stub-only detection are enforced
by the AC traceability gate before the generated audit artifact is uploaded.

Fixture-only fake AC IDs in script tests are classified separately in the
generated AC-to-EPIC mismatch report.

## Historical Audits

| Report | Date | Scope | Status |
|---|---|---|---|
| [AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) | 2026-05-04 | Vision -> EPIC -> AC consistency | Historical; superseded for current metrics by generated AC coverage report |
| [archive/AC-AUDIT-2026-02-25.md](./archive/AC-AUDIT-2026-02-25.md) | 2026-02-25 | AC numbering compliance | Archived; lineage folded into EPIC-014 |
| [archive/AC-TEST-TRACEABILITY-AUDIT.md](./archive/AC-TEST-TRACEABILITY-AUDIT.md) | 2026-02 era | Test -> AC traceability | Archived; legacy inventory superseded by generated registry/report tooling |

## Audit Rules

1. Current counts should come from scripts, not hand-maintained prose.
2. New project audits should explain what was checked and link to generated
   evidence.
3. When an audit finds work that belongs in code or tests, create an issue and
   reference it instead of encoding future behavior in prose.

## Retired Standalone Reports

The root `TESTING_GAP_ANALYSIS.md` report was retired during the 2026-05-20
documentation cleanup. Its old hand-written testing narrative duplicated
`docs/ssot/tdd.md`, `docs/ssot/coverage.md`, `docs/ssot/ci-cd.md`, and the
generated AC coverage report. Current testing gaps are tracked by issues
[#454](https://github.com/wangzitian0/finance_report/issues/454) and
[#456](https://github.com/wangzitian0/finance_report/issues/456).

`docs/project/archive/**` was swept on 2026-05-20. Useful archive content is
now owned by active EPICs:

| Archive Source | Current Owner |
|---|---|
| `EPIC-002-*` | EPIC-002 archive integration notes |
| `EPIC-004.reconciliation-accuracy-report.md` | EPIC-004 issues and archive integration notes |
| `EPIC-ENCODING-SUMMARY.md` | EPIC-011, EPIC-012, EPIC-013, EPIC-014 |
| `EPIC-QA-Standardization.md`, `QA_REPORT_20260121.md` | EPIC-012 and EPIC-014 |
| `TEST-COVERAGE-PLAN.md`, `testing-gap-analysis.md`, `testing-implementation.md` | EPIC-008 and generated coverage reports |
| AC audit archives | This audit index and EPIC-014 |

Related cleanup issues:

- [#453](https://github.com/wangzitian0/finance_report/issues/453)
- [#454](https://github.com/wangzitian0/finance_report/issues/454)
- [#455](https://github.com/wangzitian0/finance_report/issues/455)
- [#456](https://github.com/wangzitian0/finance_report/issues/456)
