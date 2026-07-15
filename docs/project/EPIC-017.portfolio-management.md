# EPIC-017: Investment Portfolio Management (100% Self-Developed)
<!-- epic-file: design-doc -->

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-1-portfolio-self-developed`
> **Phase**: 5 (Asset Tracking)
> **Planning estimate**: 6-8 weeks
> **Priority**: P1 (High Priority - Post Two-Stage Review)
> **Dependencies**: EPIC-002 (Double-Entry Core), EPIC-003 (Statement Parsing), EPIC-011 (Asset Lifecycle P0)
> **Usable milestone**: ⏸️ deferred (post-Usable). Investment portfolio is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1) (upload a year of real data on prod).

---

## 🎯 Objective

Build a **100% self-developed** investment portfolio management system with comprehensive holdings tracking, performance metrics, and brokerage statement auto-parsing. This is a fully integrated, self-hosted solution.

**Core Features**:
- **Holdings Dashboard**: Ticker, quantity, cost basis, market value, P&L
- **Performance Metrics**: XIRR, time-weighted return, money-weighted return
- **Asset Allocation**: Sector, geography, asset class breakdowns
- **Dividend Tracking**: Dividend income, yield calculations
- **Cost Basis Methods**: FIFO, LIFO, Average Cost
- **Brokerage Parsing**: Auto-parse Moomoo, Futu, Interactive Brokers statements

**Out of Scope** (v1):
- Trading execution (buy/sell orders)
- Real-time market data streaming
- Options/futures tracking
- Crypto wallet integration

---

## Macro Proof Ownership

- `personal-financial-report-package`
- `asset-distribution-net-worth`
- `investment-performance`
- `annualized-income-long-term`

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Data Model | Extend `atomic_positions` (EPIC-011 Layer 2) for holdings. Use `managed_positions` (Layer 3) for cost basis calculations. |
| 📊 **Accountant** | Accounting Integration | Buy/sell transactions → Journal entries. Realized P&L = Income account. Unrealized P&L = valuation adjustment. |
| 💻 **Developer** | Implementation | Extend extraction service (EPIC-003) for brokerage statements. Reuse market data service for price updates. |
| 🧪 **Tester** | Validation | Test: XIRR calculation accuracy, cost basis methods (FIFO/LIFO/AvgCost), dividend accrual, P&L reconciliation. |
| 📋 **PM** | User Experience | Dashboard = Quick overview. Detail pages for deep-dive. Manual price update UI (user updates every few months). |
| 💹 **Investor** | Domain Expert | XIRR is critical for multi-currency portfolios. Sector allocation helps rebalancing. Dividend tracking for tax reporting. |

---

## Live Status Ownership

This EPIC defines scope and acceptance criteria. Do not use unchecked boxes,
historical audit tables, or planning estimates in this file as current delivery
status. For current proof and delivery state, use:

- Generated AC registry index: `docs/ac_registry.yaml`
- Live local proof command: `python tools/analyze_test_ac_coverage.py --no-write --stdout`
- CI proof artifact: `ac-test-traceability-audit`
- North-star tracker: [#444](https://github.com/wangzitian0/finance_report/issues/444)
- Brokerage proof work: [#477](https://github.com/wangzitian0/finance_report/issues/477), [#478](https://github.com/wangzitian0/finance_report/issues/478), [#479](https://github.com/wangzitian0/finance_report/issues/479)

## Scope Management

This EPIC owns portfolio scope and AC definitions. Detailed implementation
inventories were removed because models, APIs, frontend components, and tests are
now better managed by code, SSOT files, and generated proof.

| Scope area | Owner |
|---|---|
| Holdings, cost basis, P&L, allocation, dividends | `apps/backend/src/portfolio/extension/` (`holdings.py`, `performance.py`, `allocation.py`, …), portfolio tests |
| Brokerage statement parsing and import bridge | [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md), extraction/portfolio tests |
| Asset and atomic-position model rationale | [assets.md](../../common/portfolio/assets.md), [schema.md](../../common/meta/schema.md) |
| Portfolio API surface | `apps/backend/src/routers/portfolio.py`, API contract tests |
| Portfolio UI surfaces | `apps/frontend/src/app/(main)/portfolio`, frontend tests |
| Current proof and execution stage | AC registries, `tools/check_ac_index.py`, [test-execution-matrix.yaml](../../common/testing/data/test-execution-matrix.yaml) |

Framework boundary: EPIC-017 supplies portfolio facts, not final framework
accounting conclusions. Holdings, lots, cost basis, dividends, fees, prices,
freshness, and source links are inputs to EPIC-020. Whether a US-like or HK-like
personal report presents a valuation change in a specific statement line or
disclosure belongs to EPIC-020 and EPIC-005 assembly.

Future scope such as additional brokers, complex corporate actions, options,
futures, crypto, and real-time market streaming needs explicit ACs before it can
be treated as current work.

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/portfolio/`

### AC17.1: Holdings & P&L Tracking

> **Fully migrated.** The write-side accounting/cost-basis rows are owned by
> the `portfolio` package roadmap in
> [`common/portfolio/contract.py`](../../common/portfolio/contract.py) as
> `AC-portfolio.1.1` · `AC-portfolio.1.2` ·
> `AC-portfolio.1.3` · `AC-portfolio.4.1` ·
> `AC-portfolio.4.2` · `AC-portfolio.2.1` ·
> `AC-portfolio.2.2` · `AC-portfolio.3.1`.
>
> *(AC17.1.1 removed and AC17.1.5 removed and AC17.1.7-9 removed — the remaining read-side rows migrated to the `portfolio` package roadmap as `AC-portfolio.holdings.1-5`, migration closeout continuation, #1663 / #1717)*

> *(AC17.1.6 "Manual Price Update" removed — migrated to the `pricing`
> package roadmap as `AC-pricing.providers.1`, migration closeout
> continuation, #1663 / #1710)*

### AC17.2: Performance Metrics

> *(AC17.2.1-5 removed and AC17.2.7-9 removed — migrated to the `portfolio` package roadmap as `AC-portfolio.performance.1-8`, migration closeout continuation, #1663 / #1717)*
>
> *(AC17.2.6 removed — duplicate; it re-stated AC17.1.5's fact against the same test, canonical copy is `AC-portfolio.holdings.2`)*

### AC17.3: Asset Allocation

> *(AC17.3.1-3 removed and AC17.3.5 removed and AC17.3.7-14 removed — migrated to the `portfolio` package roadmap as `AC-portfolio.allocation.1-12`, migration closeout continuation, #1663 / #1717)*
>
> *(AC17.3.4 removed and AC17.3.6 removed — duplicates; they re-stated AC17.2.2-3's facts against the same tests, canonical copies are `AC-portfolio.performance.2-3`)*

### AC17.4: Brokerage Statement Parsing

> **Partially migrated.** The extraction-owned rows (were AC17.4.* rows
> .7/.9/.10/.11/.12/.13) are homed in the `extraction` package roadmap as
> `AC-extraction.304.7` · `AC-extraction.304.9` · `AC-extraction.304.10` · `AC-extraction.304.11` · `AC-extraction.304.12` · `AC-extraction.304.13`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py));
> the remaining rows below stay with their own owners.

> (AC17.4.1 removed and AC17.4.2 removed and AC17.4.3 removed and AC17.4.4 removed and AC17.4.5 removed and AC17.4.6 removed and AC17.4.8 removed and AC17.4.14 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.brokerage-import.1` through `.7` (AC17.4.4/AC17.4.5 merged into `.4`), #1821 Wave A)

### AC17.5: Investment Accounting (Journal Entries)

> **Fully migrated.** The write-side accounting rows are homed in the
> `portfolio` package roadmap as
> `AC-portfolio.1.1` · `AC-portfolio.1.2` ·
> `AC-portfolio.1.3` · `AC-portfolio.4.1` ·
> `AC-portfolio.4.2` · `AC-portfolio.2.1` ·
> `AC-portfolio.2.2` · `AC-portfolio.3.1`
> ([`common/portfolio/contract.py`](../../common/portfolio/contract.py)).
>
> *(AC17.5.4-8 removed — the remaining valuation-read rows migrated to the `portfolio` package roadmap as `AC-portfolio.valuation.1-5`, migration closeout continuation, #1663 / #1717)*

### AC17.6: Integration & End-to-End

> **Fully migrated.** The investment-accounting lifecycle rows are
> package-owned as `AC-portfolio.2.1` and
> `AC-portfolio.4.1`
> ([`common/portfolio/contract.py`](../../common/portfolio/contract.py)).
>
> *(AC17.6.3-21 removed — the API rows migrated to the `portfolio` package roadmap as `AC-portfolio.api.1-19`, migration closeout continuation, #1663 / #1717)*

### AC17.8: Brokerage Import Completion UI

(AC17.8.1 removed and AC17.8.2 removed and AC17.8.3 removed and AC17.8.4 removed and AC17.8.5 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.11` through `.15`, #1821 Wave B)

### AC17.9: Point-in-Time Portfolio Snapshots

> *(AC17.9.1 removed and AC17.9.2 removed — migrated to the `portfolio`
> package roadmap as `AC-portfolio.as-of.1-2`; the frontend row below stays
> here. Migration closeout continuation, #1663 / #1717.)*

(AC17.9.3 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.16`, #1821 Wave B)

### AC17.10: Investment Performance Report Schedule API

This API contract is the EPIC-017-owned schedule input for the personal
financial-report package tracked by #564. It is intentionally separate from
the dashboard-only `/api/portfolio/performance` summary so EPIC-005 can consume
a stable, report-ready payload with source traceability and explanation fields.

Endpoint:
`GET /api/portfolio/performance/report-schedule?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD&as_of_date=YYYY-MM-DD&currency=SGD`

When dates are omitted, the API defaults to year-to-date reporting using
`period_end=today`, `period_start=January 1` of the period-end year, and
`as_of_date=period_end`.

Response object:

| Field | Meaning |
|---|---|
| `period_start`, `period_end`, `as_of_date`, `currency` | Schedule boundary and presentation currency |
| `xirr`, `time_weighted_return`, `money_weighted_return` | Portfolio performance metrics as percentages |
| `realized_pnl`, `unrealized_pnl`, `dividend_income`, `dividend_yield` | Decimal-safe return components |
| `holdings` | Per holding `{asset_identifier, quantity, cost_basis, market_value, unrealized_pnl, realized_pnl, dividend_income, currency}` rows |
| `allocation` | Sector, geography, and asset-class allocation rows |
| `data_freshness` | Market-data source, latest price date, stale flag, `stale_holdings` per-holding stale list, and manual override basis |
| `source_links` | Source document, brokerage import, price source, and ledger/report traceability anchors |
| `notes` | Human-readable methods and limitations for cost basis, market prices, and return metrics |

When no holding snapshot exists on or before the requested `as_of_date`, the
report schedule may use active current holdings only if the same asset has a
manual market-data override dated after `as_of_date`. This is report-preparation
evidence for EPIC-005 packaging, not a mutation or relaxation of historical
portfolio queries, and the response must disclose the override through notes,
freshness metadata, and source links.

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.report-schedule.1-6` (migration closeout continuation,
> #1663 / #1717).

### AC17.11: Portfolio Financial Logic Audit Fixes

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.logic-audit.1-4` (migration closeout continuation, #1663 /
> #1717).

### AC17.12: Portfolio Audit Fixture Expansion

This block owns the deterministic portfolio fixture contract used by the
personal financial-report package proof. Local real PDF/CSV inputs may be used
to learn statement structure, but committed fixtures must be synthetic,
redacted, and Decimal-safe.

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.fixtures.1-3` (migration closeout continuation, #1663 /
> #1717).

### AC17.13: Portfolio Fact Boundary for Framework Reporting

Portfolio management owns holdings, lots, dividends, fees, and source
links, and relays price/freshness facts (owned by the `pricing` package,
#1610) as framework policy inputs, but
does not own final US/HK report presentation decisions.

> This group's row removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.fact-boundary.1` (migration closeout continuation, #1663 /
> #1717).

### AC17.14: Unified Portfolio Allocation Surface

This started as the first frontend slice for #914 and now uses the report-owned
net-worth allocation schedule for the allocation surface. The investment
performance schedule remains the source for period return, unrealized
market-value gain/loss, and price freshness.

(AC17.14.1 removed and AC17.14.3 removed and AC17.14.4 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-assets2.17` through `.19`, #1821 Wave B)
> (AC17.14.2 removed, canonical: migrated to the `reporting` package roadmap
> as `AC-reporting.net-worth-components.3`, #1821 Wave A)

### AC17.15: Non-Ticker Identifier Guard

Brokerage fund positions (e.g. money-market funds) store the full fund name as
`asset_identifier`. That free text was sent to Yahoo Finance as a ticker, 404ing
on every lookup. The guard skips guaranteed-404 Yahoo requests for non-ticker
identifiers (these positions are valued from their existing AtomicPosition
snapshot). The unpriced-drop skip is intentionally kept at `debug` to honor the
high-volume audit-noise contract (AC-observability.8.4); surfacing dropped positions to the
user (e.g. a report blocker) is tracked as follow-up. Issue #1035.

> This group's rows removed — migrated to the `pricing` package roadmap as
> `AC-pricing.providers.2-3` (migration closeout continuation, #1663 /
> #1710).

### AC17.30: List Endpoint Pagination

The portfolio list endpoints (`/holdings`, `/{ticker}/dividends`,
`/{ticker}/realized`, and the three `/allocation/*` surfaces) returned unbounded
`list[...]` payloads with no `limit`/`offset` bounds, the lone gap versus the
statement/journal/account/reconciliation modules (issue #1007). Bounded
`limit`/`offset` query params now apply a sane default cap
(`limit` defaults to 100, `ge=1, le=500`; `offset` `ge=0`, matching the accounts
module). FastAPI rejects out-of-range values with 422. The bare-array response
shape is preserved so existing frontend consumers keep working without coordinated
changes; wrapping these responses in `{items, total}` is deferred to a follow-up
that also migrates the frontend consumers.

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.pagination.1-6` (migration closeout continuation, #1663 /
> #1717).

### Brokerage PDF to Asset Report Proof Matrix

This is the detailed EPIC-017 counterpart to the README core proof path. It
keeps the product path, EPIC ownership, AC ownership, executable proof, and CI
tier in one place for the Moomoo/Futu brokerage PDF to asset report journey.
EPIC-008 remains the owner of the provider-backed staging AI/OCR gate.

| Product path step | EPIC owner | AC owner | Executable proof | File | CI tier |
|---|---|---|---|---|---|
| Upload Moomoo/Futu brokerage PDF through `/api/statements/upload` | EPIC-008 / EPIC-013 | AC-extraction.813.10 | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value` | `tests/e2e/test_brokerage_upload_to_portfolio_value.py` | Post-merge staging AI/OCR gate |
| Background parse detects brokerage payload and imports positions without a manual API call | EPIC-017 | AC-extraction.304.7 / AC-portfolio.valuation.1 / AC-extraction.813.10 | `test_parse_statement_background_imports_brokerage_positions` | `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py` | Backend shard |
| Brokerage-style OCR balance mismatches remain parsed and visible instead of stalling | EPIC-008 / EPIC-017 | AC-extraction.813.10 | `test_parse_document_routes_brokerage_balance_mismatch_to_parsed` | `apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py` | Backend shard |
| Concurrent auto parse import and manual statement import share the same deduped position instead of failing with a duplicate-key 500 | EPIC-017 | AC-portfolio.brokerage-import.6 | `test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| Statement-scoped import creates holdings | EPIC-017 | AC-portfolio.brokerage-import.5 / AC-extraction.813.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| Imported holdings affect balance sheet value | EPIC-005 / EPIC-017 | AC-portfolio.valuation.1 / AC-extraction.813.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | `apps/backend/tests/portfolio/test_brokerage_position_parsing.py` | Backend shard |
| User completes import and navigates to portfolio value | EPIC-017 | AC-portfolio.fe-assets2.11 / `.12` / `.14` | completes parsed statement import and portfolio value navigation (exact title in the package roadmap `test=`) | `apps/frontend/src/__tests__/brokerageImportCompletionFlow.test.tsx` | Frontend test |

Provider-backed gate details live in
[EPIC-008](EPIC-008.testing-strategy.md#ac813-tier-3-browser-e2e-full-statement-journey) and
[CI/CD SSOT](../../common/runtime/ci-cd.md#deploy-e2e-gates). The README keeps
the compact entry-point version of this matrix.

### Personal Report Package Dependency

[#564](https://github.com/wangzitian0/finance_report/issues/564) delivered the
investment performance schedule proof path needed by the personal
financial-report package tracked in
[#563](https://github.com/wangzitian0/finance_report/issues/563). This EPIC
supplies holdings, cost basis, realized and unrealized P&L, dividends,
allocation, and as-of valuation schedules in a form that EPIC-005 consumes as
the `investment_performance` section.
[#596](https://github.com/wangzitian0/finance_report/issues/596) owns the
proof-status promotion after #594.

For #521 closure, this EPIC should be sequenced as:

1. Consume the package section contract from `#570`.
2. Done: finalize the investment-performance inputs and schedule (`#564`).
3. Land supporting explanation assets:
   - report notes (`#571`)
   - traceability appendix (`#572`)
4. Provide deterministic fixture inputs for the package proof (`#573`).
5. Done: extend the implemented `#565` post-merge package proof with the
   report-ready investment schedule, now
   `AC-reporting.package-investment.1`, `AC-reporting.fe-viz-reports.2`, and
   `AC-portfolio.report-schedule.1-2` after the package-roadmap migration.

The post-merge proof test is owned by EPIC-008.

## Current Scope Decisions

The detailed v1/v2 roadmap, deliverable checklist, technical debt table, and
clarification Q&A were removed as hand-maintained status snapshots. The durable
scope decisions are:

| Decision | Current owner |
|---|---|
| Portfolio is self-developed, not outsourced to a portfolio SaaS | `vision.md` decision 1 and this EPIC objective |
| XIRR/TWR/MWR, allocation, dividends, and cost basis are in portfolio scope | `AC-portfolio.holdings/performance/allocation/valuation/api/report-schedule/logic-audit.*` (`common/portfolio/contract.py`) |
| Brokerage statements are uploaded and parsed through the statement pipeline | AC17.4, EPIC-003/EPIC-013 extraction SSOT |
| Manual price update remains valid for low-frequency holdings; provider sync is governed separately | `AC-pricing.providers.1`, `AC-pricing.marketdata.1-11` (`common/pricing/contract.py`) — price/valuation data ownership moved to the `pricing` package (#1610); portfolio consumes prices, it does not own them |
| Report-ready investment schedule is consumed by the personal report package | `AC-portfolio.report-schedule.*` and EPIC-005 package contract |
| Framework-specific report presentation for portfolio facts is not owned here | [framework-reporting.md](../../common/reporting/framework-reporting.md), EPIC-020, AC17.13 |

Current proof status comes from generated registries, traceability checks, tests,
critical proof matrix rows, and CI artifacts. Open product questions should be
tracked as issues or new ACs, not as pending prose.

## Historical Audit Notes

The April 2026 FE/UI audit snapshot was removed from this EPIC. Current portfolio UI scope is represented by the AC group below and executable frontend tests.

---

## 🆕 UI Gap Audit (April 2026) — Dividends, Cost Basis, Realized P&L Frontend

**Origin**: UI gap audit against [Project Vision](../target.md) decision 1 (100% self-developed portfolio with XIRR/TWR/MWR, dividend tracking, cost basis methods). Backend portfolio APIs are planned but the frontend has no surfaces for dividend history, cost-basis selection, or realized P&L per holding.

### Acceptance Criteria

All former dividends, cost-basis, and realized-P&L criteria are canonical in
the `portfolio` package roadmap as `AC-portfolio.fe-assets2.20` through `.24`
(#1821 Wave B / #1858). The dividends AC absorbs the row-label proof and
directly backs the `decision-1-portfolio-self-developed` vision anchor.

**Priority**: P1 — depends on backend portfolio API delivery; surfaces vision-critical metrics.
**Estimated effort**: 5-7 days frontend (3 tabs + cost-basis selector + summary additions); backend dividend/realized endpoints tracked in core EPIC-017 scope.

### AC17.31: Portfolio Typed Responses ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. `POST /portfolio/prices/update` and `PATCH /portfolio/{ticker}`
declare typed Pydantic responses (`PriceUpdateBatchResponse`,
`CostBasisMethodUpdateResponse`) instead of raw `dict`, so the response contract is
visible in OpenAPI and the generated frontend client.

> This group's rows removed — migrated to the `portfolio` package roadmap as
> `AC-portfolio.typed-responses.1-2` (migration closeout continuation,
> #1663 / #1717).

### AC17.32: Brokerage CSV Routing — migrated to the `extraction` package ([#1255](https://github.com/wangzitian0/finance_report/issues/1255))

CSV uploads previously routed every `.csv` through the bank transaction parser,
so brokerage CSVs (positions/holdings or trade-history schemas) failed with a
misleading generic "No valid transactions found" error and never reached
`BrokeragePositionImportService`. A header-shape classifier now runs BEFORE bank
CSV parsing: a brokerage **positions** CSV is mapped into a `positions` payload
that flows into the brokerage import path, and a brokerage **trade-history** CSV
(out of scope for mapping) is rejected with an actionable unsupported-document
error instead of the misleading bank parse failure. Bank CSV parsing is
unchanged for non-brokerage schemas.

> **The ACs of this group are no longer defined here.** The rows (were
> AC17.32.* rows .1–.3) migrated into the `extraction` package and are owned
> by, and sourced directly from,
> [`common/extraction/contract.py`](../../common/extraction/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-extraction.<group>.<seq>` id scheme
> (`AC17.32.<s>` becomes
> `AC-extraction.332.<s>`). `common/meta/extension/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-extraction.332.<s>` ids (homed in the package roadmap):
> `AC-extraction.332.1` · `AC-extraction.332.2` · `AC-extraction.332.3`

### AC17.33: Non-US / multi-currency correctness ([#1441](https://github.com/wangzitian0/finance_report/issues/1441))

The system implicitly assumed a US-market / USD world. Hong Kong equities are
stored by their numeric exchange code (e.g. "01810"); sent verbatim to Yahoo /
Stooq they 404, so non-US holdings got no live or historical price and the
net-worth trend flat-lined at cost basis. Separately, an auto-created brokerage
account was stamped with a hardcoded `USD` currency regardless of the holding's
actual currency. The outbound provider symbol is now exchange-qualified
(`<4-digit>.HK`) without changing the stored symbol scope, and a new broker
account adopts the currency of the holding that created it.

> *(AC17.33.1 removed and AC17.33.2 removed — Yahoo/Stooq HK numeric-code symbol mapping migrated to the `pricing` package roadmap as `AC-pricing.providers.4-5`, migration closeout continuation, #1663 / #1710)*

> (AC17.33.3 removed, canonical: migrated to the `portfolio` package roadmap
> as `AC-portfolio.brokerage-import.8`, #1821 Wave A)

### AC17.34: Signed (Short) Positions ([#1448](https://github.com/wangzitian0/finance_report/issues/1448))

A margin/options account holds short positions — a directly-shorted stock or a sold option — with **negative quantity AND negative market value** (e.g. sold puts). `quantity` was already unconstrained and the reconcile loop already "handles negative quantities", but two inconsistent CHECK constraints (`ck_atomic_positions_market_value_non_negative`, `ck_managed_positions_cost_basis_non_negative`) blocked the matching negative value and crashed the import with a 500. Both constraints are dropped (migration `0052_signed_positions`), so a short imports as a first-class signed position that *reduces* portfolio value. Valuation/net-worth aggregation is already sign-correct for a net-long account (price × signed quantity, summed); allocation/XIRR edge cases that arise only when a portfolio's **total** is net-negative are tracked separately. The earlier "skip the short" stop-gap (which dropped real positions) is removed.

> (AC17.34.1 removed, canonical: migrated to the `portfolio` package roadmap
> as `AC-portfolio.brokerage-import.9`, #1821 Wave A)
