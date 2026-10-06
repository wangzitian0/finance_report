# EPIC-003: Smart Statement Parsing

<!-- epic-file: goal-stub -->

> **Status**: ✅ Complete — shipped and cut over to the `extraction` package.
> **Vision Anchor**: `decision-2-event-middle-layer`
> **Goal**: extract settlement, statement, PDF, and CSV facts into validated transactions and candidate entries.

All ACs, contracts, and roadmaps are owned by the `extraction` package:
[`common/extraction/contract.py`](../../common/extraction/contract.py) and [`common/extraction/readme.md`](../../common/extraction/readme.md).
Failed parsing cases are tracked in [`extraction_failed_case_registry`](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/audit-failed-cases.yaml) (AC-extraction.9.1).
This file is a goal stub kept as a product anchor; it defines no AC rows.

## Macro Proof Ownership

- `source-ledger-report-traceability`

## Framework Boundary

EPIC-003 owns source capture. It extracts settlement, statement, PDF, and CSV facts with source metadata, period boundaries, currencies, balances, and raw line anchors needed by downstream evidence checks. It does not decide US-like or HK-like report classification, measurement, presentation, or disclosure.
