# EPIC-020: Framework-Aware Personal Financial Reporting

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Phase**: Target-backward report policy
> **Priority**: P0 for US/HK framework selection on personal financial reports
> **Dependencies**: EPIC-002, EPIC-003, EPIC-005, EPIC-017, EPIC-018, EPIC-019
> **Usable milestone**: ⏸️ deferred (post-Usable). Framework-aware US/HK report policy is owned here but **not** required for the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1); a single trustworthy report is enough to be usable — framework selection comes after.

---

## Objective

Define the target-backward accounting policy layer that lets a user upload all
settlement evidence and generate a personal financial-report package by choosing
`personal_us_gaap_like` or `personal_hkfrs_like`.

This EPIC does not claim statutory US GAAP, SEC, HKEX, or HKFRS filing
compliance. It owns framework-aware personal management reporting: deterministic
recognition, measurement, classification, presentation, and disclosure rules
that borrow discipline from US and Hong Kong reporting frameworks.

## Macro Proof Ownership

- `personal-financial-report-package`

## MECE Audit Architecture

The six audit lanes are mutually exclusive by question and collectively cover
the stated product goal.

| Lane | Direction | Owner | EPIC-020 dependency |
|---|---|---|---|
| Source capture | Fact-forward | EPIC-003 / EPIC-013 | Consumes parsed settlement facts and source metadata |
| Evidence control | Fact-forward | EPIC-019, with EPIC-004 reconciliation signals | Consumes readiness blockers and review state |
| Canonical ledger | Fact-forward | EPIC-002 | Consumes framework-neutral journal entries and balances |
| Portfolio subledger | Fact-forward | EPIC-017 | Consumes holdings, lots, dividends, fees, and valuation evidence |
| Framework policy | Target-backward | EPIC-020 | Owns US/HK target policy and required evidence |
| Report assembly | Target-backward | EPIC-005 | Produces statements, notes, exports, and traceability from policy results |

EPIC-018 is a cross-cutting AI capability. It can suggest measurement and
disclosure evidence, but trusted output must be deterministic, reviewed, and
traceable.

## Scope

Owned here:

- Supported framework IDs: `personal_us_gaap_like` and `personal_hkfrs_like`.
- Framework target package requirements: required statements, schedules, notes,
  line mappings, and blocker conditions.
- Policy matrix for recognition, measurement, classification, presentation, and
  disclosure.
- Read-only policy result contract consumed by EPIC-005.
- Required evidence definitions that EPIC-019 readiness must evaluate.
- AI boundary rules for measurement/disclosure suggestions.

Not owned here:

- Parsing settlement files (EPIC-003 / EPIC-013).
- It does not parse settlements.
- Reconciliation scoring or review UI (EPIC-004 / EPIC-016).
- Posting canonical journal entries (EPIC-002).
- Maintaining portfolio lots, holdings, or market data (EPIC-017 / EPIC-011).
- Rendering report pages or exports (EPIC-005).
- AI prompt execution or model integration (EPIC-018).

## Reporting Pipeline Authority (CODE / LLM)

The personal-report pipeline is three layers, each declaring whether its used
artifact is produced by CODE or by the LLM (see `docs/ssot/authority-tiers.md`).
Authority is assigned by *who emits the artifact that is used*, and it dictates the
layer's valid proof type. This is the deterministic-by-construction spine of the
report: LLM judgement is confined to the one layer where polymorphism is
irreducible, and code holds final authority everywhere a number becomes financial
truth.

| Layer | What it decides | Authority | Who emits the used artifact | Proof obligation | Enforcing gate |
|---|---|---|---|---|---|
| **event → L2** | classify a financial event (category, direction) — polymorphic | **LLM** | LLM emits the classification; code does enum + balance/dedup sanity and may reject, never author | invariant / property + eval + provenance; **no exact-golden** | LLM cassette balance-chain drift gate (`tools/check_llm_cassettes.py`, AC23.7.1) |
| **L2 → L1** | map an L2 category to a report line | **CODE** | code's deterministic rule table emits the line; LLM only fills ambiguous knobs (`holding_intent` / `horizon`, `OTHER` disambiguation) and code validates | assert the **code's** decision, not the LLM output | L2→L1 completeness gate (`test_framework_policy_coverage.py`, AC20.8.1) |
| **L1 → report** | aggregate by the L1 registry into statements | **CODE** | code sums by registry; no LLM in the path; bit-reproducible | exact / property test | pending — L1 registry + exact-aggregation test (tracked separately) |

Notes:
- **L2 → L1 is CODE today** (the `framework_policy` rule table is pure deterministic
  code, zero LLM). The LLM may later fill only the `holding_intent` / `horizon`
  judgement knob under code validation; the rule table stays code-authoritative, so
  the layer's used artifact is still emitted by code.
- The **L1 → report** exact proof requires the enumerated L1 registry, which is the
  one piece blocked on the reporting taxonomy template; until then this layer's
  exact-aggregation proof is pending.

## Acceptance Criteria

### AC20.1: Framework Target Registry

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.1.1 | Framework reporting SSOT defines `personal_us_gaap_like` and `personal_hkfrs_like`, excludes CN/CAS v1, and states that outputs are personal management reports rather than statutory filings | `test_AC20_1_1_framework_registry_defines_us_hk_personal_targets` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC20.2: MECE Direction Ownership

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.2.1 | Framework reporting SSOT and EPIC-020 define the six-lane fact-forward/target-backward architecture with distinct owners and outputs | `test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC20.3: Target-backward Report Requirements

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.3.1 | Framework target package requirements enumerate required statements, report line mappings, policy dimensions, evidence anchors, disclosure requirements, and blocker conditions before report assembly | `test_AC20_3_1_framework_target_contract_is_report_output_backward` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC20.4: Personal Finance Policy Matrix

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.4.1 | The v1 policy matrix covers cash, listed securities, funds, dividends, brokerage fees, FX, restricted compensation, property, mortgage, and private/manual assets across recognition, measurement, classification, presentation, and disclosure | `test_AC20_4_1_policy_matrix_covers_personal_finance_domains` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC20.5: Read-Only Policy Result

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.5.1 | Framework policy consumes canonical ledger, portfolio facts, evidence readiness, and framework target without mutating source records, journal entries, portfolio lots, market data, or report snapshots | `test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC20.6: AI Measurement and Disclosure Boundary

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.6.1 | AI measurement/disclosure suggestions can affect trusted output only after becoming structured fields with source anchor, confidence tier, review state, policy field name, and accepted value; package UI requires explicit framework selection before loading framework-scoped output | `test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields`, `test_AC20_6_1_ai_suggestions_require_reviewed_policy_fields_for_readiness`, `AC20.6.1 requires explicit framework selection before loading framework-scoped package output` | `tests/tooling/test_framework_reporting_epic_contract.py`, `reporting/test_framework_package_integration.py`, `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |

### AC20.7: Framework-Differentiated Proof Path

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.7.1 | The same settlement and portfolio fixture must be able to produce US-like and HK-like personal report packages with framework-specific line mappings, notes, source anchors, export metadata, and readiness blockers | `test_AC20_7_1_same_fixture_must_drive_framework_differentiated_reports`, `test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs`, `AC20.6.1 AC20.7.1 loads readiness and policy result with the selected framework` | `tests/tooling/test_framework_reporting_epic_contract.py`, `reporting/test_framework_policy.py`, `frontend/src/__tests__/personalReportPackagePage.test.tsx` | P0 |

### AC20.8: L2→L1 Line-Mapping Completeness

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.8.1 | Every L2 category — each `AssetType` and each `ManualValuationComponentType` — resolves to a concrete L1 report line via the framework policy matrix in both `personal_us_gaap_like` and `personal_hkfrs_like`; a known category landing in the `UNSUPPORTED`/gap path fails the gate, so report assembly never improvises a line for a known category (`BOND`/`OTHER` regression covered) | `test_AC20_8_1_every_asset_type_maps_to_an_l1_line`, `test_AC20_8_1_every_manual_component_maps_to_an_l1_line`, `test_AC20_8_1_bond_and_other_are_mapped_not_gaps` | `reporting/test_framework_policy_coverage.py` | P0 |

### AC20.9: Reporting Pipeline Authority Tiers

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC20.9.1 | EPIC-020 declares the three reporting-pipeline layers (`event → L2`, `L2 → L1`, `L1 → report`) each with its CODE/LLM authority and valid proof obligation; LLM authority is confined to the `event → L2` layer and code holds final authority where a number becomes financial truth | `test_AC20_9_1_reporting_pipeline_declares_layer_authority_tiers` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

## Implementation Order

1. Define the framework policy result schema and SSOT contract.
2. Add framework-aware readiness blockers before adding rendered output.
3. Add policy matrix tests over the expanded settlement/portfolio fixture.
4. Add report assembly consumption tests for US-like and HK-like outputs.
5. Expose framework selection in the package API and UI after backend proof is
   deterministic.

## Tracking Issues

- Umbrella: [#675](https://github.com/wangzitian0/finance_report/issues/675)
- Policy result schema: [#676](https://github.com/wangzitian0/finance_report/issues/676)
- US/HK policy matrix v1: [#677](https://github.com/wangzitian0/finance_report/issues/677)
- Framework-aware readiness blockers: [#678](https://github.com/wangzitian0/finance_report/issues/678)
- Framework selection UI and exports: [#679](https://github.com/wangzitian0/finance_report/issues/679)
- Report package API integration: [#680](https://github.com/wangzitian0/finance_report/issues/680)
- US/HK golden fixture proof: [#681](https://github.com/wangzitian0/finance_report/issues/681)

## Related

- [framework-reporting.md](../ssot/framework-reporting.md)
- [reporting.md](../ssot/reporting.md)
- [accounting.md](../ssot/accounting.md)
- [EPIC-005](./EPIC-005.reporting-visualization.md)
- [EPIC-017](./EPIC-017.portfolio-management.md)
