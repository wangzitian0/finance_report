# AC Coverage Analysis Report

> Generated: 2026-05-20 06:22:55 UTC by `scripts/analyze_test_ac_coverage.py`

## Coverage accounting (EPIC-008 aligned)

- Covered AC = has at least one real test reference outside `apps/backend/tests/_ac_stubs/`.
- `_ac_stubs` references are tracked as placeholders (`stub-only`) and **do not** count as covered.
- Invalid AC references are AC IDs found in tests but missing from registries.
- Untested AC = registered AC without any real passing-test candidate reference.

## Executive summary

| Metric | Count |
|---|---:|
| Registered ACs | 953 |
| Covered by real test candidates | 710 (74.5%) |
| Stub-only placeholders (`_ac_stubs`) | 225 |
| Registered but untested | 243 |
| Invalid AC refs in real tests | 2 |
| Invalid AC refs in stubs | 0 |

## Scan scope summary

| Source | Files scanned | Unique AC refs (real) | Unique AC refs (stub) |
|---|---:|---:|---:|
| backend | 178 | 534 | 363 |
| frontend | 81 | 176 | 0 |
| e2e | 9 | 11 | 0 |
| repo_e2e | 18 | 0 | 0 |

## Coverage by EPIC

| EPIC | Name | Registered | Covered | Stub-only | Untested | Coverage |
|---|---|---:|---:|---:|---:|---:|
| EPIC-001 | phase0-setup | 29 | 19 | 10 | 10 | 65.5% |
| EPIC-002 | double-entry-core | 59 | 52 | 7 | 7 | 88.1% |
| EPIC-003 | statement-parsing | 39 | 33 | 6 | 6 | 84.6% |
| EPIC-004 | reconciliation-engine | 39 | 34 | 5 | 5 | 87.2% |
| EPIC-005 | reporting-visualization | 36 | 30 | 6 | 6 | 83.3% |
| EPIC-006 | ai-advisor | 63 | 52 | 11 | 11 | 82.5% |
| EPIC-007 | deployment | 39 | 6 | 33 | 33 | 15.4% |
| EPIC-008 | testing-strategy | 82 | 65 | 0 | 17 | 79.3% |
| EPIC-009 | pdf-fixture-generation | 37 | 0 | 36 | 37 | 0.0% |
| EPIC-010 | signoz-logging | 21 | 0 | 21 | 21 | 0.0% |
| EPIC-011 | asset-lifecycle | 38 | 38 | 0 | 0 | 100.0% |
| EPIC-012 | foundation-libs | 62 | 52 | 10 | 10 | 83.9% |
| EPIC-013 | statement-parsing-v2 | 60 | 54 | 6 | 6 | 90.0% |
| EPIC-014 | ttd-transformation | 6 | 0 | 6 | 6 | 0.0% |
| EPIC-015 | processing-account | 28 | 28 | 0 | 0 | 100.0% |
| EPIC-016 | two-stage-review-ui | 213 | 155 | 58 | 58 | 72.8% |
| EPIC-017 | portfolio-management | 79 | 79 | 0 | 0 | 100.0% |
| EPIC-018 | ai-driven-pipeline | 23 | 13 | 10 | 10 | 56.5% |

## Invalid AC references (unregistered)

| AC ID | Real test files | Stub files |
|---|---|---|
| `AC8.12.7` | `apps/backend/tests/extraction/test_extraction_error_paths.py` | _none_ |
| `AC18.4.4` | `apps/backend/tests/reporting/test_reporting_net_worth_components.py` | _none_ |

## Stub-only AC placeholders (`_ac_stubs`)

| AC ID | Stub file references |
|---|---|
| `AC1.2.3` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.2.4` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.2.5` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.3.2` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.3.3` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.4.3` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.4.4` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.5.3` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.5.4` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC1.5.5` | `apps/backend/tests/_ac_stubs/test_epic_01_stubs.py` |
| `AC2.2.6` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.4.3` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.4.4` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.4.5` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.5.3` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.9.2` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC2.9.4` | `apps/backend/tests/_ac_stubs/test_epic_02_stubs.py` |
| `AC3.2.1` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC3.2.2` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC3.3.1` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC3.3.2` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC3.3.3` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC3.5.3` | `apps/backend/tests/_ac_stubs/test_epic_03_stubs.py` |
| `AC4.6.1` | `apps/backend/tests/_ac_stubs/test_epic_04_stubs.py` |
| `AC4.6.2` | `apps/backend/tests/_ac_stubs/test_epic_04_stubs.py` |
| `AC4.6.3` | `apps/backend/tests/_ac_stubs/test_epic_04_stubs.py` |
| `AC4.6.4` | `apps/backend/tests/_ac_stubs/test_epic_04_stubs.py` |
| `AC4.6.5` | `apps/backend/tests/_ac_stubs/test_epic_04_stubs.py` |
| `AC5.6.1` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC5.6.2` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC5.6.3` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC5.6.4` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC5.6.5` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC5.6.6` | `apps/backend/tests/_ac_stubs/test_epic_05_stubs.py` |
| `AC6.1.2` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.1.3` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.1.4` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.2.3` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.2.4` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.1` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.2` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.3` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.4` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.5` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC6.12.6` | `apps/backend/tests/_ac_stubs/test_epic_06_stubs.py` |
| `AC7.1.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.1.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.1.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.2.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.2.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.2.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.2.4` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.2.5` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.3.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.3.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.3.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.3.4` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.3.5` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.4` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.5` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.4.6` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.5.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.5.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.5.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.5.4` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.5.5` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.6.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.1` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.2` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.3` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.4` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.5` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.6` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.7` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC7.9.8` | `apps/backend/tests/_ac_stubs/test_epic_07_stubs.py` |
| `AC9.1.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.1.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.1.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.1.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.1.5` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.1.6` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.5` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.6` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.2.7` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.5` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.3.6` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.4.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.4.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.4.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.4.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.5.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.5.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.5.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.5.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.5.5` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.6.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.6.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.6.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.6.4` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.6.5` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.7.1` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.7.2` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC9.7.3` | `apps/backend/tests/_ac_stubs/test_epic_09_stubs.py` |
| `AC10.1.1` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.1.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.1.3` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.2.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.4.1` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.4.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.5.1` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.5.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.5.3` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.5.4` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.6.1` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.6.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.6.3` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.6.4` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.1` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.2` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.3` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.4` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.5` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.6` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC10.7.7` | `apps/backend/tests/_ac_stubs/test_epic_10_stubs.py` |
| `AC12.19.1` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.22.1` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.22.2` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.23.1` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.23.2` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.23.3` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.23.4` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.24.1` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.24.2` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC12.24.3` | `apps/backend/tests/_ac_stubs/test_epic_12_stubs.py` |
| `AC13.10.1` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC13.10.2` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC13.10.3` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC13.10.4` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC13.10.5` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC13.10.6` | `apps/backend/tests/_ac_stubs/test_epic_13_stubs.py` |
| `AC14.1.1` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC14.1.2` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC14.1.3` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC14.1.4` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC14.1.5` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC14.1.6` | `apps/backend/tests/_ac_stubs/test_epic_14_stubs.py` |
| `AC16.1.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.1.2` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.1.3` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.2.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.2.2` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.2.3` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.2.4` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.5.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.10.5` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.2` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.3` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.4` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.5` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.6` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.7` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.8` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.9` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.10` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.11` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.12` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.13` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.14` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.15` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.16` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.17` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.18` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.19` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.20` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.21` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.22` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.23` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.24` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.25` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.26` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.27` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.28` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.29` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.30` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.11.31` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.2` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.3` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.4` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.5` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.6` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.7` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.8` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.9` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.10` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.11` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.13.12` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.1` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.2` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.3` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.4` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.5` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC16.22.6` | `apps/backend/tests/_ac_stubs/test_epic_16_stubs.py` |
| `AC18.1.1` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.1.2` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.1.3` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.1.4` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.1.5` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.1.6` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.3.2` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.3.3` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.4.1` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |
| `AC18.4.2` | `apps/backend/tests/_ac_stubs/test_epic_18_stubs.py` |

## Registered ACs with no real test reference

### EPIC-001 (phase0-setup) — 10 untested

`AC1.2.3`, `AC1.2.4`, `AC1.2.5`, `AC1.3.2`, `AC1.3.3`, `AC1.4.3`, `AC1.4.4`, `AC1.5.3`, `AC1.5.4`, `AC1.5.5`

### EPIC-002 (double-entry-core) — 7 untested

`AC2.2.6`, `AC2.4.3`, `AC2.4.4`, `AC2.4.5`, `AC2.5.3`, `AC2.9.2`, `AC2.9.4`

### EPIC-003 (statement-parsing) — 6 untested

`AC3.2.1`, `AC3.2.2`, `AC3.3.1`, `AC3.3.2`, `AC3.3.3`, `AC3.5.3`

### EPIC-004 (reconciliation-engine) — 5 untested

`AC4.6.1`, `AC4.6.2`, `AC4.6.3`, `AC4.6.4`, `AC4.6.5`

### EPIC-005 (reporting-visualization) — 6 untested

`AC5.6.1`, `AC5.6.2`, `AC5.6.3`, `AC5.6.4`, `AC5.6.5`, `AC5.6.6`

### EPIC-006 (ai-advisor) — 11 untested

`AC6.1.2`, `AC6.1.3`, `AC6.1.4`, `AC6.2.3`, `AC6.2.4`, `AC6.12.1`, `AC6.12.2`, `AC6.12.3`, `AC6.12.4`, `AC6.12.5`, `AC6.12.6`

### EPIC-007 (deployment) — 33 untested

`AC7.1.1`, `AC7.1.2`, `AC7.1.3`, `AC7.2.1`, `AC7.2.2`, `AC7.2.3`, `AC7.2.4`, `AC7.2.5`, `AC7.3.1`, `AC7.3.2`, `AC7.3.3`, `AC7.3.4`, `AC7.3.5`, `AC7.4.1`, `AC7.4.2`, `AC7.4.3`, `AC7.4.4`, `AC7.4.5`, `AC7.4.6`, `AC7.5.1`, `AC7.5.2`, `AC7.5.3`, `AC7.5.4`, `AC7.5.5`, `AC7.6.2`, `AC7.9.1`, `AC7.9.2`, `AC7.9.3`, `AC7.9.4`, `AC7.9.5`, `AC7.9.6`, `AC7.9.7`, `AC7.9.8`

### EPIC-008 (testing-strategy) — 17 untested

`AC8.13.6`, `AC8.13.7`, `AC8.13.8`, `AC8.13.11`, `AC8.13.12`, `AC8.13.13`, `AC8.13.14`, `AC8.13.15`, `AC8.13.16`, `AC8.13.17`, `AC8.13.20`, `AC8.13.21`, `AC8.13.22`, `AC8.13.23`, `AC8.13.24`, `AC8.13.25`, `AC8.13.26`

### EPIC-009 (pdf-fixture-generation) — 37 untested

`AC9.1.1`, `AC9.1.2`, `AC9.1.3`, `AC9.1.4`, `AC9.1.5`, `AC9.1.6`, `AC9.2.1`, `AC9.2.2`, `AC9.2.3`, `AC9.2.4`, `AC9.2.5`, `AC9.2.6`, `AC9.2.7`, `AC9.3.1`, `AC9.3.2`, `AC9.3.3`, `AC9.3.4`, `AC9.3.5`, `AC9.3.6`, `AC9.3.7`, `AC9.4.1`, `AC9.4.2`, `AC9.4.3`, `AC9.4.4`, `AC9.5.1`, `AC9.5.2`, `AC9.5.3`, `AC9.5.4`, `AC9.5.5`, `AC9.6.1`, `AC9.6.2`, `AC9.6.3`, `AC9.6.4`, `AC9.6.5`, `AC9.7.1`, `AC9.7.2`, `AC9.7.3`

### EPIC-010 (signoz-logging) — 21 untested

`AC10.1.1`, `AC10.1.2`, `AC10.1.3`, `AC10.2.2`, `AC10.4.1`, `AC10.4.2`, `AC10.5.1`, `AC10.5.2`, `AC10.5.3`, `AC10.5.4`, `AC10.6.1`, `AC10.6.2`, `AC10.6.3`, `AC10.6.4`, `AC10.7.1`, `AC10.7.2`, `AC10.7.3`, `AC10.7.4`, `AC10.7.5`, `AC10.7.6`, `AC10.7.7`

### EPIC-012 (foundation-libs) — 10 untested

`AC12.19.1`, `AC12.22.1`, `AC12.22.2`, `AC12.23.1`, `AC12.23.2`, `AC12.23.3`, `AC12.23.4`, `AC12.24.1`, `AC12.24.2`, `AC12.24.3`

### EPIC-013 (statement-parsing-v2) — 6 untested

`AC13.10.1`, `AC13.10.2`, `AC13.10.3`, `AC13.10.4`, `AC13.10.5`, `AC13.10.6`

### EPIC-014 (ttd-transformation) — 6 untested

`AC14.1.1`, `AC14.1.2`, `AC14.1.3`, `AC14.1.4`, `AC14.1.5`, `AC14.1.6`

### EPIC-016 (two-stage-review-ui) — 58 untested

`AC16.1.1`, `AC16.1.2`, `AC16.1.3`, `AC16.2.1`, `AC16.2.2`, `AC16.2.3`, `AC16.2.4`, `AC16.5.1`, `AC16.10.5`, `AC16.11.1`, `AC16.11.2`, `AC16.11.3`, `AC16.11.4`, `AC16.11.5`, `AC16.11.6`, `AC16.11.7`, `AC16.11.8`, `AC16.11.9`, `AC16.11.10`, `AC16.11.11`, `AC16.11.12`, `AC16.11.13`, `AC16.11.14`, `AC16.11.15`, `AC16.11.16`, `AC16.11.17`, `AC16.11.18`, `AC16.11.19`, `AC16.11.20`, `AC16.11.21`, `AC16.11.22`, `AC16.11.23`, `AC16.11.24`, `AC16.11.25`, `AC16.11.26`, `AC16.11.27`, `AC16.11.28`, `AC16.11.29`, `AC16.11.30`, `AC16.11.31`, `AC16.13.1`, `AC16.13.2`, `AC16.13.3`, `AC16.13.4`, `AC16.13.5`, `AC16.13.6`, `AC16.13.7`, `AC16.13.8`, `AC16.13.9`, `AC16.13.10`, `AC16.13.11`, `AC16.13.12`, `AC16.22.1`, `AC16.22.2`, `AC16.22.3`, `AC16.22.4`, `AC16.22.5`, `AC16.22.6`

### EPIC-018 (ai-driven-pipeline) — 10 untested

`AC18.1.1`, `AC18.1.2`, `AC18.1.3`, `AC18.1.4`, `AC18.1.5`, `AC18.1.6`, `AC18.3.2`, `AC18.3.3`, `AC18.4.1`, `AC18.4.2`
