# EPIC-020: Framework-Aware Personal Financial Reporting

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1719): reporting/extraction specs live in common/reporting/readme.md and common/extraction/readme.md. -->

> **Status**: Design Doc (deferred post-Usable)
> **Vision Anchor**: `decision-filter-accuracy-auditability`

Defines target-backward accounting policy (`personal_us_gaap_like` and `personal_hkfrs_like`, not a statutory filing) in [common/reporting/framework-reporting.md](../../common/reporting/framework-reporting.md).

## Macro Proof Ownership

- `personal-financial-report-package`

## MECE Audit Architecture & Scope

The six audit lanes are mutually exclusive and collectively cover the pipeline:

| Lane | Direction | Owner |
|---|---|---|
| Source capture | Fact-forward | EPIC-003 / EPIC-013 (parses settlements; EPIC-020 does not parse settlements) |
| Evidence control | Fact-forward | EPIC-019 / EPIC-004 |
| Canonical ledger | Fact-forward | EPIC-002 |
| Portfolio subledger | Fact-forward | EPIC-017 |
| Framework policy | Target-backward | EPIC-020 (recognition, measurement, classification, presentation, disclosure) |
| Report assembly | Target-backward | EPIC-005 (evidence anchors, statements, exports) |

### Target-backward Report Requirements

Framework target package requirements enumerate required statements, line mappings, policy dimensions (`recognition`, `measurement`, `classification`, `presentation`, `disclosure`), evidence anchors, and readiness blockers before assembly. The same settlement and portfolio fixture must produce US-like and HK-like personal report packages with framework-specific line mappings, notes, and readiness blockers.

### AI Measurement and Disclosure Boundary

AI suggestions become trusted only via structured, reviewed policy fields with source anchors, confidence tiers, and accepted values.

## Reporting Pipeline Authority Tiers

Each layer binds an authority tier (`common/meta/readme.md`):

- `event → L2`: **LLM-LED** — invariant/property + eval + provenance, no exact-golden (`tests/benchmarks/pdf_corpus_oracle.py`).
- `L2 → L1`: **CODE-LED** (CODE-ONLY today via `framework_policy`) — assert the **code's** decision (`test_framework_policy_coverage.py`).
- `L1 → report`: **CODE-ONLY** — pure code aggregation, exact / property test.

## Related

- [common/reporting/framework-reporting.md](../../common/reporting/framework-reporting.md) · [common/reporting/readme.md](../../common/reporting/readme.md) · [common/ledger/readme.md](../../common/ledger/readme.md)
