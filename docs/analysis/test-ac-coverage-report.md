# AC Coverage Analysis Report

> Generated: 2026-05-26 09:35:12 UTC by `scripts/analyze_test_ac_coverage.py`
> Snapshot: this checked-in report is a generated artifact. Regenerate it or inspect CI artifacts for current values; do not copy these counts into prose docs.

## Coverage accounting (EPIC-008 aligned)

- Covered AC = has at least one real test reference outside `_ac_stubs`, trivial placeholder assertions, pure `pass`, and pure skipped tests.
- `expect(true).toBe(true)`, pure `pass`, and pure skipped references are tracked as placeholder-only and **do not** count as covered.
- `_ac_stubs` references are tracked as placeholders (`stub-only`) and **do not** count as covered.
- Strikethrough deprecated ACs are excluded from active coverage and untested counts.
- Synthetic AC IDs inside `scripts/tests` fixtures are excluded from invalid-ref counts; fixture-only mismatches are audited separately.
- Invalid AC references are other AC IDs found in tests but missing from registries.
- Untested AC = registered AC without any real passing-test candidate reference.

## Executive summary

| Metric | Count |
|---|---:|
| Registered ACs | 989 |
| Active ACs | 986 |
| Deprecated ACs excluded from coverage gate | 3 |
| Covered by real test candidates | 986 (100.0%) |
| Placeholder-only assertions | 0 |
| Stub-only placeholders (`_ac_stubs`) | 0 |
| Active registered but untested | 0 |
| Invalid AC refs in real tests | 0 |
| Invalid AC refs in placeholders | 0 |
| Invalid AC refs in stubs | 0 |

## Scan scope summary

| Source | Files scanned | Unique AC refs (real) | Unique AC refs (placeholder) | Unique AC refs (stub) |
|---|---:|---:|---:|---:|
| backend | 167 | 648 | 0 | 0 |
| frontend | 79 | 189 | 7 | 0 |
| scripts_tests | 46 | 200 | 23 | 0 |
| e2e | 11 | 22 | 0 | 0 |
| repo_e2e | 18 | 0 | 0 | 0 |

## Coverage by EPIC

| EPIC | Name | Registered | Deprecated | Covered | Placeholder-only | Stub-only | Untested | Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| EPIC-001 | phase0-setup | 29 | 0 | 29 | 0 | 0 | 0 | 100.0% |
| EPIC-002 | double-entry-core | 59 | 0 | 59 | 0 | 0 | 0 | 100.0% |
| EPIC-003 | statement-parsing | 47 | 0 | 47 | 0 | 0 | 0 | 100.0% |
| EPIC-004 | reconciliation-engine | 39 | 0 | 39 | 0 | 0 | 0 | 100.0% |
| EPIC-005 | reporting-visualization | 36 | 0 | 36 | 0 | 0 | 0 | 100.0% |
| EPIC-006 | ai-advisor | 63 | 0 | 63 | 0 | 0 | 0 | 100.0% |
| EPIC-007 | deployment | 39 | 0 | 39 | 0 | 0 | 0 | 100.0% |
| EPIC-008 | testing-strategy | 99 | 0 | 99 | 0 | 0 | 0 | 100.0% |
| EPIC-009 | pdf-fixture-generation | 37 | 0 | 37 | 0 | 0 | 0 | 100.0% |
| EPIC-010 | signoz-logging | 21 | 0 | 21 | 0 | 0 | 0 | 100.0% |
| EPIC-011 | asset-lifecycle | 38 | 0 | 38 | 0 | 0 | 0 | 100.0% |
| EPIC-012 | foundation-libs | 62 | 3 | 59 | 0 | 0 | 0 | 100.0% |
| EPIC-013 | statement-parsing-v2 | 60 | 0 | 60 | 0 | 0 | 0 | 100.0% |
| EPIC-014 | ttd-transformation | 6 | 0 | 6 | 0 | 0 | 0 | 100.0% |
| EPIC-015 | processing-account | 31 | 0 | 31 | 0 | 0 | 0 | 100.0% |
| EPIC-016 | two-stage-review-ui | 217 | 0 | 217 | 0 | 0 | 0 | 100.0% |
| EPIC-017 | portfolio-management | 82 | 0 | 82 | 0 | 0 | 0 | 100.0% |
| EPIC-018 | ai-driven-pipeline | 24 | 0 | 24 | 0 | 0 | 0 | 100.0% |

## Invalid AC references (unregistered)

No invalid AC references found.

## Stub-only AC placeholders (`_ac_stubs`)

No stub-only AC placeholders found.

## Placeholder-only AC assertions

No placeholder-only AC assertions found.

## Active registered ACs with no real test reference

All active registered ACs have at least one real test reference.
