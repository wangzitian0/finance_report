# `portfolio` — Investment Position Accounting

Owns position quantities, cost basis (`FIFO`/`LIFO`/`AVGCOST` via `InvestmentLot`), `ManagedPosition` (`orm/portfolio.py`), `InvestmentTransaction`, and `DividendIncome` (`apps/backend/src/portfolio/`). Composes `ledger.post_entry` for double-entry cash/P&L entries and `pricing.resolve` for market valuations (never stores market prices or FX rates directly).

## Services & Reconciliation

- **Write (`extension/accounting.py`)**: `InvestmentAccountingService` exposes `post_buy`, `post_sell`, `post_dividend` using `TradeOrder`, `TradeAccounts`, and `DividendEvent`, ensuring open quantity `>= 0` and deterministic `source_type=system` entries (`common/audit/readme.md#source-type-trust-hierarchy-provenance`).
- **Atomic -> Managed (`extension/positions.py`)**: Windowed latest `AtomicPosition` per `(asset_identifier, broker)` upserts `ACTIVE` `ManagedPosition` rows and marks absent holdings `DISPOSED` (never deleted). Historical `as_of_date` checks `acquisition_date <= as_of_date < disposal_date`.
- **Read (`extension/{holdings,allocation,performance,performance_report}.py`)**: Computes XIRR/TWR/MWR, dividend yield, allocation, and FX-converted P&L via `pricing` (`PricingError` on missing rates). Use `Decimal`, never `float`.
