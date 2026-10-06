# EPIC-017: Investment Portfolio Management (100% Self-Developed)

<!-- epic-file: goal-stub -->

> **Status**: ✅ Complete — shipped and cut over to the `portfolio` package.
> **Vision Anchor**: `decision-1-portfolio-self-developed`
> **Goal**: build self-developed investment portfolio management with holdings tracking, performance metrics, and brokerage statement auto-parsing.

All ACs, contracts, and roadmaps are owned by the `portfolio` package:
[`common/portfolio/contract.py`](../../common/portfolio/contract.py) and [`common/portfolio/readme.md`](../../common/portfolio/readme.md).
This file is a goal stub kept as a product anchor; it defines no AC rows.

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `investment-performance`
- `annualized-income-long-term`

## Framework boundary

The portfolio package supplies portfolio facts as inputs to EPIC-020; presentation belongs to EPIC-020 and EPIC-005 assembly. The portfolio subsystem does not own final US/HK report presentation decisions.

## Investment Performance Reporting Schedule

The schedule endpoint `GET /api/portfolio/performance/report-schedule` returns:
- Query parameters: `period_start`, `period_end`, `as_of_date`, `currency`
- Performance and position fields: `xirr`, `time_weighted_return`, `money_weighted_return`, `realized_pnl`, `unrealized_pnl`, `dividend_income`, `dividend_yield`, `holdings`, `allocation`, `data_freshness`, `stale_holdings`, `source_links`, `notes`.
