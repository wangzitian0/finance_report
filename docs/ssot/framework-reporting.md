# Framework-Aware Personal Reporting SSOT

> **SSOT Key**: `framework_reporting`
> **Core Definition**: Target-backward accounting framework policy for
> US-like and HK-like personal financial-report packages.

---

## 1. Objective

The product goal is:

```text
Upload all settlement evidence -> choose US-like or HK-like framework ->
generate a trusted personal financial-report package.
```

This is not a statutory filing, audit opinion, tax filing, or listed-company
annual report. The framework names mean personal management reports that borrow
recognition, measurement, presentation, and disclosure discipline from US GAAP
and HKFRS-style reporting.

Supported v1 framework IDs:

- `personal_us_gaap_like`
- `personal_hkfrs_like`

Explicitly out of scope for v1:

- CN/CAS framework output.
- SEC, HKEX, XBRL, audit opinion, consolidated issuer reporting, or regulated
  filing compliance.

## 2. Direction Matrix

The architecture uses both fact-forward and target-backward reasoning. Each lane
has a different question, owner, and proof responsibility.

| Lane | Direction | Owner | Question | Output |
|---|---|---|---|---|
| Source capture | Fact-forward | EPIC-003 / EPIC-013 | What did the settlement, statement, PDF, or CSV say? | Parsed facts with source metadata |
| Evidence control | Fact-forward | EPIC-019, with EPIC-004 reconciliation signals | Is the evidence complete, reviewed, and conflict-free enough for a trusted report? | Readiness state and blockers |
| Canonical ledger | Fact-forward | EPIC-002 | How do facts become balanced double-entry records? | Framework-neutral journal entries and account balances |
| Portfolio subledger | Fact-forward | EPIC-017 | What are the investment holdings, lots, dividends, fees, and valuation facts? | Portfolio facts and valuation evidence |
| Framework policy | Target-backward | EPIC-020 | What must a US-like or HK-like report require from the facts? | Recognition, measurement, classification, presentation, and disclosure policy result |
| Report assembly | Target-backward | EPIC-005 | How is the policy result rendered as a complete personal report package? | Statements, schedules, notes, export, and traceability appendix |

EPIC-018 is cross-cutting. AI can help identify measurement evidence and draft
disclosure suggestions, but it does not own trusted monetary results or final
framework policy decisions.

## 3. Framework Policy Contract

For each supported framework and report period, the policy layer must derive a
structured result from canonical facts:

```text
canonical ledger + portfolio facts + evidence readiness + framework target
  -> framework policy result
```

The result must include:

- stable policy result ID.
- framework ID and report period.
- required statements and schedules.
- report line mappings.
- recognition basis per source event type.
- measurement basis per asset/liability/income category.
- disclosure requirements and blocker conditions.
- source, ledger, portfolio, valuation, and review anchors.

The policy layer is read-only. It must not mutate source records, journal
entries, portfolio lots, market data, or report snapshots.

Code-owned contract surfaces:

- Schema: `apps/backend/src/schemas/reporting.py` defines supported framework
  IDs, policy fact domains, required policy dimensions, evidence anchors,
  policy decisions, explicit gaps, matrices, and policy results.
- Matrix service: `apps/backend/src/services/framework_policy.py` owns the
  deterministic v1 US-like/HK-like matrix, builds framework-neutral facts from
  existing user accounts, atomic positions, manual valuations, dividends, and
  market-data overrides, then derives read-only policy results.
- Package API: `GET /api/reports/package/framework-policy` returns the selected
  framework policy result consumed by package assembly. `GET
  /api/reports/package/contract` exposes supported framework IDs, the selected
  framework ID when provided, and the policy result endpoint. `GET
  /api/reports/package/readiness` accepts the same selected framework inputs and
  evaluates framework policy blockers before marking output trusted.
- Proof: `apps/backend/tests/reporting/test_framework_policy.py` verifies that
  policy results reject missing dimensions, unsupported frameworks are closed
  out, supported domains carry all five policy dimensions, derivation is
  deterministic/read-only, US/HK outputs can differ from the same fixture, and
  unsupported instruments create explicit policy gaps instead of silently
  defaulting to market value.
  `apps/backend/tests/reporting/test_framework_package_integration.py` covers
  package API framework selection, DB-derived policy results, readiness
  blockers, and reviewed AI policy-field requirements.

## 4. Minimum V1 Policy Matrix

The first framework matrix must cover these personal finance domains:

| Domain | Required policy dimensions |
|---|---|
| Cash and bank accounts | Classification, period cutoff, source coverage |
| Listed equities and ETFs | Measurement basis, unrealized gain presentation, stale price disclosure |
| Funds and money-market products | Classification, valuation source, liquidity disclosure |
| Dividends and interest | Recognition date, income line mapping, withholding/tax note hooks |
| Brokerage fees | Cost basis or expense treatment, cash-flow presentation |
| FX | Transaction-date, average-rate, and period-end-rate usage by statement type |
| RSU, ESOP, and options | Recognition trigger, restriction/liquidity treatment, valuation evidence |
| Property, mortgage, and private/manual assets | Valuation basis, source date, confidence, and trusted-total blocker rules |

## 5. AI Boundary

AI may produce structured suggestions for measurement and disclosure, including:

- likely asset category.
- proposed valuation basis.
- source uncertainty.
- disclosure draft text.
- fair-value evidence hints.

Those suggestions can influence trusted output only after they are transformed
into deterministic structured fields with:

- source anchor.
- confidence tier.
- review state.
- policy field name.
- accepted value.

The report assembly layer must never calculate trusted monetary totals from free-form AI text.

## 6. Readiness and Blockers

Framework-aware report readiness must block trusted output when any selected
framework requires evidence that is missing or unresolved, including:

- missing settlement/source coverage for an in-scope account or broker.
- overlapping or duplicate source periods.
- balance mismatch or unresolved parsing validation failure.
- pending review or reconciliation blocker.
- missing valuation basis for manual/private assets included in trusted totals.
- stale market data without an explicit freshness disclosure.
- AI-only measurement or disclosure suggestion that has not been accepted into
  structured policy fields.

Required framework-aware blocker codes:

- `unsupported_framework`: selected framework ID is outside the supported v1
  enum.
- `missing_framework_policy_result`: selected framework has report-supporting
  inputs but no matching structured policy result.
- `unsupported_policy_domain`: a framework-neutral fact has no deterministic
  v1 rule for the selected framework.
- `framework_policy_missing_dimensions`: a decision lacks recognition,
  measurement, classification, presentation, or disclosure.
- `framework_ai_suggestion_unreviewed`: AI-suggested policy fields are not
  accepted structured fields with anchors and accepted values.
- `missing_valuation_basis`: manual/private valuation snapshots included in
  trusted totals lack an explicit valuation basis.
- `stale_market_data`: listed security, ETF, mutual-fund, or bond positions
  lack market prices dated within 90 days of the report date.

Draft output may exist with blockers, but trusted output must expose the blocker
state before presenting framework-specific statements as reliable.

## 7. Relationship To Existing Reporting

EPIC-005 remains the report package assembler. It consumes the policy result and
renders statements, notes, exports, and traceability. It does not own
recognition, measurement, or framework-specific classification rules.

EPIC-020 owns framework target policy. It does not parse settlements, post
journal entries, maintain lots, or render UI.
