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

## Atomic-to-managed reconciliation (`PositionService`, shipped, pre-#1643 read side)

*(Internalized from `docs/ssot/assets.md`, migration closeout wave 3, #1664 —
this is now the single owner; do not re-add a separate SSOT copy. This
describes the currently-shipped `apps/backend/src/portfolio/extension/positions.py` (was `services/assets.py`, split per #1677)
behavior, which the #1643 read-side migration folds into this package's
`extension`/`data` layers.)*

`AtomicPosition` (Layer 2, raw broker snapshots) reconciles into
`ManagedPosition` (Layer 3, deduplicated latest position per asset) via a
window-function strategy: for each `(asset_identifier, broker)` group, pick
the row with the latest `snapshot_date` (`ROW_NUMBER() OVER (PARTITION BY
asset_identifier, broker ORDER BY snapshot_date DESC) WHERE rn = 1`).

**Reconcile → upsert**, for each latest atomic position: skip if `quantity`
or `market_value` is `NULL` (recorded in `skipped_assets`); look up the
existing `ManagedPosition` by `(user_id, account_id, asset_identifier)`;
update if found (refresh quantity/cost_basis/currency/metadata, clear
disposal); create if not found (new `ACTIVE` position with an
auto-created broker account); dispose any existing managed position not
seen in the latest snapshot (`status=DISPOSED`, `disposal_date=today`).
`_get_or_create_broker_account` auto-creates an `ASSET`-type account per
broker (falls back to `"Unknown Broker"` when unnamed). Reconciliation is
idempotent — running twice with the same data produces the same result.

`ReconcileResult`: `created`/`updated`/`disposed`/`skipped` counts +
`skipped_assets` (identifiers). Edge cases: `quantity`/`market_value` NULL
→ skipped; `quantity == 0` → treated as disposal; `quantity < 0` → treated
normally (short positions); `broker` NULL/empty → `"Unknown Broker"`;
position absent from snapshot → `DISPOSED` with `disposal_date = today`.

**Latest holdings valuation date** — `GET /portfolio/holdings` without
`as_of_date` returns the latest value from `ManagedPosition` plus the
latest eligible price snapshot; the valuation date is `today` unless the
user's latest imported `AtomicPosition.snapshot_date` is newer (current-
month brokerage fixtures / provider outputs that normalize month-only
periods to month end). Explicit `as_of_date` requests are point-in-time:
holdings derive from the latest immutable `AtomicPosition` snapshot per
`(asset_identifier, broker)` at or before the requested date — future
snapshots are never used. `InvestmentTransaction`/`InvestmentLot` provide
the auditable cost-basis trail when structured brokerage transactions
exist; snapshot-only imports fall back to market value as the cost-basis
proxy.

**Investment accounting pipeline** (posted through
`InvestmentAccountingService`): Buy — debit the investment asset account,
credit brokerage cash, create an `InvestmentTransaction` + `InvestmentLot`,
increase `ManagedPosition.quantity`/`cost_basis`. Sell — consume open lots
by the explicit `CostBasisMethod` (`FIFO`/`LIFO`/`AvgCost`), debit
brokerage cash, credit the investment asset account at consumed cost
basis, record realized gain/loss to the realized-P&L income account,
update `ManagedPosition.realized_pnl`. Dividend — debit brokerage cash,
credit dividend income, persist `DividendIncome`, link the event via
`InvestmentTransaction`. Investment-accounting journal entries use
`source_type=system` for deterministic postings, preserving any upstream
parser/source identifier in `source_id`; user-entered/parsed/matched/
confirmed statement entries follow the trust hierarchy in
[`docs/ssot/source-type-priority.md`](../../docs/ssot/source-type-priority.md).

**Portfolio performance cash flows** use investment-domain cash flows
only: XIRR and money-weighted return use `InvestmentTransaction` rows up
to `as_of_date`; time-weighted return removes only investment-domain cash
flows in the measurement period; general bank `AtomicTransaction` rows
(salary, bills, transfers, ...) are excluded. BUY is an investor cash
outflow for XIRR and a positive TWR contribution; SELL/DIVIDEND are
investor cash inflows for XIRR and negative TWR withdrawals. Portfolio
summary YTD realized P&L and dividend income are presentation-currency
values — each transaction/dividend converts from its source currency on
its transaction/payment date before aggregation.

**Depreciation** — two methods on a single `ManagedPosition`:
straight-line (`period_depreciation = (cost_basis - salvage_value) /
useful_life_years`) and double-declining balance
(`period_depreciation = (2 / useful_life_years) × book_value`, where
`book_value = cost_basis - accumulated_depreciation`).
`DepreciationResult`: `position_id`, `asset_identifier`,
`period_depreciation`, `accumulated_depreciation`, `book_value`, `method`
(`"straight_line"`/`"declining_balance"`), `useful_life_years`,
`salvage_value`.

**Data model** (mutable table/column/enum/index/FK inventory is generated
from SQLAlchemy metadata — see the generated DB schema reference; models
live in `apps/backend/src/models/layer3.py` and
`apps/backend/src/models/portfolio.py`):

| Model | Table | Domain role |
|---|---|---|
| `ManagedPosition` | `managed_positions` | DWS maintained position state derived from source snapshots and investment transactions |
| `InvestmentTransaction` | `investment_transactions` | Auditable brokerage buy/sell/dividend event used for ledger posting and realized P&L |
| `InvestmentLot` | `investment_lots` | Lot-level cost-basis state for FIFO/LIFO/average-cost realized P&L |

(`ManualValuationSnapshot` moved to
[`common/pricing/readme.md`](../pricing/readme.md#manual-valuation-snapshots)
— it's a valuation fact, not position math.)

Design constraints: use `Decimal` for all monetary/quantity fields, never
`float`; prefer `InvestmentLot` for realized P&L whenever buy/sell
transactions are available, snapshot market value only as a fallback
proxy for position-snapshot-only imports; always record `position_metadata`
(JSONB) for the source-data audit trail; never delete positions — mark
`DISPOSED` instead; never assume a `managed_position.py` module — the
model lives in `layer3.py`.
