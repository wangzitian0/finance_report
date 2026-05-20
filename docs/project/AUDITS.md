# Audit Index

This file indexes project consistency and traceability audits. Use generated
reports for current metrics.

## Current Generated Reports

| Report | Purpose |
|---|---|
| [../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md) | Current AC-to-test coverage, stub-only ACs, untested ACs, invalid AC references |

Current generated AC snapshot:

- 960 registered ACs
- 717 ACs with real test-candidate references
- 243 registered ACs without real test reference
- 223 stub-only placeholders
- 2 invalid AC refs in real tests

Placeholder assertion detection is not yet enforced; see
[#452](https://github.com/wangzitian0/finance_report/issues/452).

AC-to-EPIC mismatch cleanup and invalid real-test AC references are tracked in
[#456](https://github.com/wangzitian0/finance_report/issues/456).

## Historical Audits

| Report | Date | Scope | Status |
|---|---|---|---|
| [AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) | 2026-05-04 | Vision -> EPIC -> AC consistency | Historical; superseded for current metrics by generated AC coverage report |
| [archive/AC-AUDIT-2026-02-25.md](./archive/AC-AUDIT-2026-02-25.md) | 2026-02-25 | AC numbering compliance | Archived |
| [archive/AC-TEST-TRACEABILITY-AUDIT.md](./archive/AC-TEST-TRACEABILITY-AUDIT.md) | 2026-02 era | Test -> AC traceability | Archived; legacy AC inventory |

## Audit Rules

1. Current counts should come from scripts, not hand-maintained prose.
2. New project audits should explain what was checked and link to generated
   evidence.
3. When an audit finds work that belongs in code or tests, create an issue and
   reference it instead of encoding future behavior in prose.

Related cleanup issues:

- [#452](https://github.com/wangzitian0/finance_report/issues/452)
- [#453](https://github.com/wangzitian0/finance_report/issues/453)
- [#454](https://github.com/wangzitian0/finance_report/issues/454)
- [#455](https://github.com/wangzitian0/finance_report/issues/455)
- [#456](https://github.com/wangzitian0/finance_report/issues/456)
