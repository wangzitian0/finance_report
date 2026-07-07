# `portfolio` — investment position accounting (domain package)

> Package model: [`../meta/readme.md`](../meta/readme.md). Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/portfolio/` directory is the **spec + review surface**; the
> conforming implementation lives at
> [`apps/backend/src/portfolio`](../../apps/backend/src/portfolio)
> (`contract.implementations["be"]`).

## Why

Buying, selling, and receiving a dividend on an investment needs the same
double-entry discipline as any other cash movement, plus position bookkeeping
double-entry doesn't cover: which lot did this sale consume, at what cost
basis, realized vs unrealized. `portfolio` owns that position math; it posts
through `ledger.post_entry` for the cash/equity side rather than duplicating
posting logic.

## Positions-only boundary (2026-07-06, updated after the pricing design review #1610)

`portfolio` owns only position math — quantity, cost basis, realized/unrealized
P&L. It never fetches or stores a price or a valuation; it *consumes* one via
`pricing.resolve(subject, as_of, policy)`. The old `MarketDataOverride` write
path (`PortfolioService.update_market_prices`) belongs to `pricing.record_override`
now, not here.

## Ubiquitous language

- **`ManagedPosition`** — portfolio's aggregate root: an open or closed holding
  in one asset, for one user/account. Owns `InvestmentLot` and
  `InvestmentTransaction`; the invariant is *open position quantity ≥ 0* plus
  cost-basis consistency across lots.
- **`InvestmentLot`** — one FIFO/LIFO/AVGCOST-consumable acquisition slice of a
  position, carrying its own cost basis.
- **`InvestmentTransaction`** — a buy/sell/dividend event against a position.
- **`DividendIncome`** — a dividend receipt, split into cash and (optionally)
  withholding-tax legs on the ledger side.
- **`AtomicPosition`** — the brokerage-extraction-facing read shape `extraction`
  feeds into position accounting (see
  [`../extraction/readme.md`](../extraction/readme.md#brokerage-position-import)).

## Write side (real, tested)

`InvestmentAccountingService` (`extension/accounting.py`) composes
`ledger.post_entry`: `post_buy`/`post_sell`/`post_dividend` each post a
balanced `Entry` and update the position's own aggregate in the same
transaction — portfolio writes its own aggregate, ledger posts on receipt, no
shared FK (Decision B). `post_sell` supports FIFO, LIFO, and AVGCOST lot
consumption and never drives an open position's quantity below zero.

## Read side (reserved — blocked on #1643)

`get_holdings`, `get_portfolio_summary`, the P&L/allocation/performance
queries, and the `PortfolioRepository` port/adapter split are declared in
[`contract.py`](./contract.py) as reserved units (no `module=`): the real
implementation still lives in `apps/backend/src/services/portfolio.py` /
`services/performance.py`, gated on the read-side migration (#1643).

## Cross-package edges

`audit` (Money/Quantity/UnitPrice base types), `ledger` (`post_entry` —
portfolio writes only its own aggregate in one transaction, then posts a
balanced `Entry`; no shared transaction), `pricing` (price/FX resolution —
portfolio never looks up a rate itself). Both `ledger` and `pricing` are L3
domain siblings; the edge is acyclic and sideways (`portfolio → ledger`,
`portfolio → pricing`, never the reverse).

## Governance

The package's write-side ACs (`AC-portfolio.1.1`–`AC-portfolio.4.2`) live in
[`contract.py`](./contract.py)'s `roadmap` and are sourced **directly** from
there into the AC registry (no EPIC mirror). The read-side ACs (still in
`docs/project/EPIC-017.portfolio-management.md`) move into this roadmap once
#1643 lands. `tools/check_package_contract.py` validates the implementation
against this contract (interface == `__all__`, every test reference resolves,
no upward import edge).
