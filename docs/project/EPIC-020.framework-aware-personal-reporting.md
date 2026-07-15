# EPIC-020: Framework-Aware Personal Financial Reporting

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1719): framework-policy scope/design record; its
     ACs migrated to the reporting package roadmap (AC-reporting.*), and
     tests/tooling/test_framework_reporting_epic_contract.py anchors the
     boundary prose kept here. -->

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

## Reporting Pipeline Authority Tiers (EPIC-026 applied)

The personal-report pipeline is three layers, each with a distinct authority tier
from the locked EPIC-026 5-tier set (see `common/meta/readme.md`). The tier
is assigned by *who emits the artifact that is used*, and it dictates the layer's
valid proof type. This is the deterministic-by-construction spine of the report:
LLM judgement is confined to the one layer where polymorphism is irreducible, and
code holds final authority everywhere a number becomes financial truth.

| Layer | What it decides | Tier | Who emits the used artifact | Proof obligation | Enforcing gate |
|---|---|---|---|---|---|
| **event → L2** | classify a financial event (category, direction) — polymorphic | **LLM-LED** (LLM-led) | LLM emits the classification; code does enum + balance/dedup sanity and may reject, never author | invariant / property + eval + provenance; **no exact-golden** | LLM cassette balance-chain drift gate (`tools/check_llm_cassettes.py`, AC-llm.7.1) |
| **L2 → L1** | map an L2 category to a report line | **CODE-LED** (code-led) — CODE-ONLY today | code's deterministic rule table emits the line; LLM only fills ambiguous knobs (`holding_intent` / `horizon`, `OTHER` disambiguation) and code validates | assert the **code's** decision, not the LLM output | L2→L1 completeness gate (`test_framework_policy_coverage.py`, `AC-reporting.pipeline.1`) |
| **L1 → report** | aggregate by the L1 registry into statements | **CODE-ONLY** (pure code) | code sums by registry; no LLM in the path; bit-reproducible | exact / property test | pending — L1 registry + exact-aggregation test (tracked separately) |

Notes:
- **L2 → L1 is CODE-ONLY today** (the `framework_policy` rule table is pure deterministic
  code, zero LLM). It becomes **CODE-LED** only when the `holding_intent` / `horizon`
  judgement knob is added; the rule table stays code-authoritative and the LLM
  fills only that knob under code validation.
- The **L1 → report** CODE-ONLY proof requires the enumerated L1 registry, which is the
  one piece blocked on the reporting taxonomy template; until then this layer's
  exact-aggregation proof is pending.

## Acceptance Criteria

> **Fully migrated** (migration closeout wave 2, #1663). Every row that used
> to live in the per-section tables below (were AC20.1.* / AC20.2.* /
> AC20.3.* / AC20.4.* / AC20.5.* / AC20.6.* / AC20.7.* / AC20.8.* /
> AC20.9.* rows) moved to a package roadmap per the standard's "AC is the
> migration unit" rule. The section headings and scope prose stay — they
> describe the product goal, not the machine-checkable AC — but each
> table is replaced by a pointer to its new home; this note references the
> new ids (keeping the registry↔EPIC link intact) but defines none of them.

### AC20.1: Framework Target Registry

Framework reporting SSOT defines `personal_us_gaap_like` and
`personal_hkfrs_like`, excludes CN/CAS v1, and states that outputs are
personal management reports rather than statutory filings.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.framework.1`.

### AC20.2: MECE Direction Ownership

Framework reporting SSOT and EPIC-020 define the six-lane fact-forward/
target-backward architecture with distinct owners and outputs, mutually
exclusive and collectively covering.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.lanes.1`.

### AC20.3: Target-backward Report Requirements

Framework target package requirements enumerate required statements,
report line mappings, policy dimensions, evidence anchors, disclosure
requirements, and blocker conditions before report assembly.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.target.1`.

### AC20.4: Personal Finance Policy Matrix

The v1 policy matrix covers cash, listed securities, funds, dividends,
brokerage fees, FX, restricted compensation, property, mortgage, and
private/manual assets across recognition, measurement, classification,
presentation, and disclosure.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.policy.1`.

### AC20.5: Read-Only Policy Result

Framework policy consumes canonical ledger, portfolio facts, evidence
readiness, and framework target without mutating source records, journal
entries, portfolio lots, market data, or report snapshots; it does not
parse settlements.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.policy.2`.

### AC20.6: AI Measurement and Disclosure Boundary

AI measurement/disclosure suggestions can affect trusted output only after
becoming structured fields with source anchor, confidence tier, review
state, policy field name, and accepted value; package UI requires explicit
framework selection before loading framework-scoped output.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.ai.1`.

### AC20.7: Framework-Differentiated Proof Path

The same settlement and portfolio fixture must be able to produce US-like and HK-like personal report packages with framework-specific line mappings, notes, source anchors, export metadata, and readiness blockers.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.framework.2`.

### AC20.8: L2→L1 Line-Mapping Completeness

Every L2 category — each `AssetType` and each `ManualValuationComponentType`
— resolves to a concrete L1 report line via the framework policy matrix in
both `personal_us_gaap_like` and `personal_hkfrs_like`; a known category
landing in the `UNSUPPORTED`/gap path fails the gate, so report assembly
never improvises a line for a known category.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.pipeline.1`.

### AC20.9: Reporting Pipeline Authority Tiers

EPIC-020 declares the three reporting-pipeline layers (`event → L2`,
`L2 → L1`, `L1 → report`) each with a locked EPIC-026 tier and its valid
proof obligation; LLM authority is confined to the LLM-LED layer and code
holds final authority where a number becomes financial truth.

> Migrated to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.pipeline.2`.
>
> Migrated to [`common/extraction/contract.py`](../../common/extraction/contract.py)'s
> `roadmap` (its test lives in the same extraction-owned file as the group's
> other members, not in `reporting`): `AC-extraction.2009.2` through
> `AC-extraction.2009.8` (`.2`–`.7` migrated in a prior PR; `.8` in this one).

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

- [framework-reporting.md](../../common/reporting/framework-reporting.md)
- [reporting.md](../../common/reporting/reporting.md)
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md)
- [EPIC-005](./EPIC-005.reporting-visualization.md)
- [EPIC-017](./EPIC-017.portfolio-management.md)
