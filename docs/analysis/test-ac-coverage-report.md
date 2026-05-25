# AC Coverage Analysis Report

> Generated: 2026-05-25 07:06:06 UTC by `scripts/analyze_test_ac_coverage.py`

## Coverage accounting (EPIC-008 aligned)

- Covered AC = has at least one real test reference outside `_ac_stubs`, trivial placeholder assertions, pure `pass`, and pure skipped tests.
- `expect(true).toBe(true)`, pure `pass`, and pure skipped references are tracked as placeholder-only and **do not** count as covered.
- `_ac_stubs` references are tracked as placeholders (`stub-only`) and **do not** count as covered.
- Invalid AC references are AC IDs found in tests but missing from registries.
- Untested AC = registered AC without any real passing-test candidate reference.

## Executive summary

| Metric | Count |
|---|---:|
| Registered ACs | 984 |
| Covered by real test candidates | 816 (82.9%) |
| Placeholder-only assertions | 0 |
| Stub-only placeholders (`_ac_stubs`) | 0 |
| Registered but untested | 168 |
| Invalid AC refs in real tests | 0 |
| Invalid AC refs in placeholders | 0 |
| Invalid AC refs in stubs | 0 |

## Scan scope summary

| Source | Files scanned | Unique AC refs (real) | Unique AC refs (placeholder) | Unique AC refs (stub) |
|---|---:|---:|---:|---:|
| backend | 166 | 628 | 0 | 0 |
| frontend | 79 | 189 | 7 | 0 |
| e2e | 10 | 16 | 0 | 0 |
| repo_e2e | 18 | 0 | 0 | 0 |

## Coverage by EPIC

| EPIC | Name | Registered | Covered | Placeholder-only | Stub-only | Untested | Coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| EPIC-001 | phase0-setup | 29 | 28 | 0 | 0 | 1 | 96.6% |
| EPIC-002 | double-entry-core | 59 | 59 | 0 | 0 | 0 | 100.0% |
| EPIC-003 | statement-parsing | 47 | 47 | 0 | 0 | 0 | 100.0% |
| EPIC-004 | reconciliation-engine | 39 | 37 | 0 | 0 | 2 | 94.9% |
| EPIC-005 | reporting-visualization | 36 | 36 | 0 | 0 | 0 | 100.0% |
| EPIC-006 | ai-advisor | 63 | 63 | 0 | 0 | 0 | 100.0% |
| EPIC-007 | deployment | 39 | 6 | 0 | 0 | 33 | 15.4% |
| EPIC-008 | testing-strategy | 94 | 71 | 0 | 0 | 23 | 75.5% |
| EPIC-009 | pdf-fixture-generation | 37 | 0 | 0 | 0 | 37 | 0.0% |
| EPIC-010 | signoz-logging | 21 | 5 | 0 | 0 | 16 | 23.8% |
| EPIC-011 | asset-lifecycle | 38 | 38 | 0 | 0 | 0 | 100.0% |
| EPIC-012 | foundation-libs | 62 | 56 | 0 | 0 | 6 | 90.3% |
| EPIC-013 | statement-parsing-v2 | 60 | 60 | 0 | 0 | 0 | 100.0% |
| EPIC-014 | ttd-transformation | 6 | 0 | 0 | 0 | 6 | 0.0% |
| EPIC-015 | processing-account | 31 | 31 | 0 | 0 | 0 | 100.0% |
| EPIC-016 | two-stage-review-ui | 217 | 173 | 0 | 0 | 44 | 79.7% |
| EPIC-017 | portfolio-management | 82 | 82 | 0 | 0 | 0 | 100.0% |
| EPIC-018 | ai-driven-pipeline | 24 | 24 | 0 | 0 | 0 | 100.0% |

## Invalid AC references (unregistered)

No invalid AC references found.

## Stub-only AC placeholders (`_ac_stubs`)

No stub-only AC placeholders found.

## Placeholder-only AC assertions

No placeholder-only AC assertions found.

## Registered ACs with no real test reference

### EPIC-001 (phase0-setup) — 1 untested

`AC1.2.3`

### EPIC-004 (reconciliation-engine) — 2 untested

`AC4.6.1`, `AC4.6.2`

### EPIC-007 (deployment) — 33 untested

`AC7.1.1`, `AC7.1.2`, `AC7.1.3`, `AC7.2.1`, `AC7.2.2`, `AC7.2.3`, `AC7.2.4`, `AC7.2.5`, `AC7.3.1`, `AC7.3.2`, `AC7.3.3`, `AC7.3.4`, `AC7.3.5`, `AC7.4.1`, `AC7.4.2`, `AC7.4.3`, `AC7.4.4`, `AC7.4.5`, `AC7.4.6`, `AC7.5.1`, `AC7.5.2`, `AC7.5.3`, `AC7.5.4`, `AC7.5.5`, `AC7.6.2`, `AC7.9.1`, `AC7.9.2`, `AC7.9.3`, `AC7.9.4`, `AC7.9.5`, `AC7.9.6`, `AC7.9.7`, `AC7.9.8`

### EPIC-008 (testing-strategy) — 23 untested

`AC8.13.6`, `AC8.13.7`, `AC8.13.8`, `AC8.13.11`, `AC8.13.12`, `AC8.13.13`, `AC8.13.14`, `AC8.13.15`, `AC8.13.16`, `AC8.13.17`, `AC8.13.20`, `AC8.13.21`, `AC8.13.22`, `AC8.13.23`, `AC8.13.24`, `AC8.13.25`, `AC8.13.26`, `AC8.13.27`, `AC8.13.33`, `AC8.13.34`, `AC8.13.35`, `AC8.13.36`, `AC8.13.37`

### EPIC-009 (pdf-fixture-generation) — 37 untested

`AC9.1.1`, `AC9.1.2`, `AC9.1.3`, `AC9.1.4`, `AC9.1.5`, `AC9.1.6`, `AC9.2.1`, `AC9.2.2`, `AC9.2.3`, `AC9.2.4`, `AC9.2.5`, `AC9.2.6`, `AC9.2.7`, `AC9.3.1`, `AC9.3.2`, `AC9.3.3`, `AC9.3.4`, `AC9.3.5`, `AC9.3.6`, `AC9.3.7`, `AC9.4.1`, `AC9.4.2`, `AC9.4.3`, `AC9.4.4`, `AC9.5.1`, `AC9.5.2`, `AC9.5.3`, `AC9.5.4`, `AC9.5.5`, `AC9.6.1`, `AC9.6.2`, `AC9.6.3`, `AC9.6.4`, `AC9.6.5`, `AC9.7.1`, `AC9.7.2`, `AC9.7.3`

### EPIC-010 (signoz-logging) — 16 untested

`AC10.1.1`, `AC10.5.1`, `AC10.5.2`, `AC10.5.3`, `AC10.5.4`, `AC10.6.1`, `AC10.6.2`, `AC10.6.3`, `AC10.6.4`, `AC10.7.1`, `AC10.7.2`, `AC10.7.3`, `AC10.7.4`, `AC10.7.5`, `AC10.7.6`, `AC10.7.7`

### EPIC-012 (foundation-libs) — 6 untested

`AC12.19.1`, `AC12.22.1`, `AC12.22.2`, `AC12.24.1`, `AC12.24.2`, `AC12.24.3`

### EPIC-014 (ttd-transformation) — 6 untested

`AC14.1.1`, `AC14.1.2`, `AC14.1.3`, `AC14.1.4`, `AC14.1.5`, `AC14.1.6`

### EPIC-016 (two-stage-review-ui) — 44 untested

`AC16.1.1`, `AC16.11.1`, `AC16.11.2`, `AC16.11.3`, `AC16.11.4`, `AC16.11.5`, `AC16.11.6`, `AC16.11.7`, `AC16.11.8`, `AC16.11.9`, `AC16.11.10`, `AC16.11.11`, `AC16.11.12`, `AC16.11.13`, `AC16.11.14`, `AC16.11.15`, `AC16.11.16`, `AC16.11.17`, `AC16.11.18`, `AC16.11.19`, `AC16.11.20`, `AC16.11.21`, `AC16.11.22`, `AC16.11.23`, `AC16.11.24`, `AC16.11.25`, `AC16.11.26`, `AC16.11.27`, `AC16.11.28`, `AC16.11.29`, `AC16.11.30`, `AC16.11.31`, `AC16.13.1`, `AC16.13.2`, `AC16.13.3`, `AC16.13.4`, `AC16.13.5`, `AC16.13.6`, `AC16.13.7`, `AC16.13.8`, `AC16.13.9`, `AC16.13.10`, `AC16.13.11`, `AC16.13.12`
