# Framework-Aware Personal Reporting SSOT

> **SSOT Key**: `framework_reporting` | Target-backward policy for `personal_us_gaap_like` and `personal_hkfrs_like` packages (not a statutory filing). **Explicitly out of scope for v1**: `CN/CAS framework output`, SEC/HKEX/XBRL filings.

## Direction Matrix

- **Source capture** (`Fact-forward`, EPIC-003/013): parsed statements/settlements.
- **Evidence control** (`Fact-forward`, EPIC-019/004): readiness & review blockers.
- **Canonical ledger** (`Fact-forward`, EPIC-002): framework-neutral journal entries.
- **Portfolio subledger** (`Fact-forward`, EPIC-017): holdings, lots, dividends, valuations.
- **Framework policy** (`Target-backward`, EPIC-020): derives `required statements and schedules`, `report line mappings`, and `disclosure requirements and blocker conditions`.
- **Report assembly** (`Target-backward`, EPIC-005): renders assembled `PersonalReportPackageDocument`.

## Read-Only Contract & Minimum V1 Policy Matrix

The policy layer (`apps/backend/src/reporting/extension/framework_policy.py`) is strictly `read-only` over `source records`, `journal entries`, `portfolio lots`, `market data`, and `report snapshots` (and `does not parse settlements`).

Covers across `recognition`, `measurement`, `classification`, `presentation`, and `disclosure`:
- `Cash and bank accounts`
- `Listed equities and ETFs`
- `Funds and money-market products`
- `Dividends and interest`
- `Brokerage fees`
- `FX`
- `RSU, ESOP, and options`
- `Property, mortgage, and private/manual assets`

## AI Boundary, Readiness Blockers & L1 Registry

- AI suggestions enter trusted output only as structured fields (`source anchor`, `confidence tier`, `review state`, `policy field name`, `accepted value`); reporting `must never calculate trusted monetary totals from free-form AI text`.
- `Framework-aware report readiness must block trusted output` on `unsupported_framework`, `missing_framework_policy_result`, `unsupported_policy_domain`, `framework_policy_missing_dimensions`, `framework_ai_suggestion_unreviewed`, `missing_valuation_basis`, or `stale_market_data` (> 90 days).
- Central L1 registry (`common/reporting/readme.md`) maps L2 categories deterministically to statement lines (`GET /api/reports/package`).
