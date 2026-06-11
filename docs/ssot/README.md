# SSOT Index

SSOT documents explain rationale, constraints, and where to find the code and
tests that own each contract. They should not duplicate implementation facts
that can be owned by code, generated schemas, config, or tests.

Project hierarchy:

```text
README.md -> EPIC -> AC -> test
```

The macro product-proof layer is separate from AC traceability:

```text
README.md -> EPIC -> E2E
```

That macro contract is owned by
[critical-proof-matrix.yaml](./critical-proof-matrix.yaml) and checked by
`tools/check_critical_proof_matrix.py`. The checker keeps the README outcome
table, matrix rows, owner EPIC declarations, and E2E proof anchors aligned.

SSOT documents support that hierarchy by explaining why a contract exists and
linking to its code owner and proof tests.

## Code Ownership Direction

When a fact is already implemented, prefer this ownership model:

| Fact type | Preferred owner | Doc role |
|---|---|---|
| Constants, thresholds, enum values | Code/config/common package | Link to owner and explain rationale |
| API request/response shape | Schemas/OpenAPI/generated client | Link to schemas and contract tests |
| State machines | Code-owned transition model plus tests | Explain lifecycle and link to transition tests |
| CI/coverage policy | common package, tools, workflows | Link to common policy, tool checks, and workflow checks |
| Operational workflow | AC + test/tool | Explain intent and link to executable proof |

The migration of code-owned SSOT facts into common packages or generated
contracts is tracked in
[issue #453](https://github.com/wangzitian0/finance_report/issues/453).

## Core System Documents

| Document | Key | Current owner role |
|---|---|---|
| [development.md](./development.md) | `development` | Developer workflow and command entry points |
| [environments.md](./environments.md) | `environments` | Environment taxonomy and isolation rationale |
| [ci-cd.md](./ci-cd.md) | `ci-cd` | CI gate semantics and workflow references |
| [deployment.md](./deployment.md) | `deployment` | Deployment model and release rationale |
| [observability.md](./observability.md) | `observability` | Structured logging and SigNoz OTLP rationale |
| [tdd.md](./tdd.md) | `tdd-transformation` | EPIC -> AC -> test workflow |
| [coverage.md](./coverage.md) | `coverage` | Coverage metric semantics; code owner is `common/coverage/policy.py` |
| [auth.md](./auth.md) | `auth` | Auth architecture rationale and code references |
| [frontend-patterns.md](./frontend-patterns.md) | `frontend-patterns` | Frontend integration rules and proof references |
| [schema.md](./schema.md) | `schema` | Database model rationale; code owner is models/migrations |
| [accounting.md](./accounting.md) | `accounting` | Double-entry rationale and invariant references |
| [MANIFEST.yaml](./MANIFEST.yaml) | `manifest` | Machine-readable concept owner registry |

## Feature Documents

| Document | Key | Current owner role |
|---|---|---|
| [extraction.md](./extraction.md) | `extraction` | Statement parsing rationale and code/test links |
| [pdf-fixtures.md](./pdf-fixtures.md) | `pdf_fixtures` | Synthetic PDF fixture commands, local-only input policy, and font fallback |
| [reconciliation.md](./reconciliation.md) | `reconciliation` | Matching rationale; thresholds should migrate to code/common |
| [reporting.md](./reporting.md) | `reporting` | Report calculation rationale and proof links |
| [framework-reporting.md](./framework-reporting.md) | `framework_reporting` | US/HK target-backward policy layer for personal report packages |
| [ai.md](./ai.md) | `ai` | Application-layer AI Advisor contract, policy, and safety rationale |
| [assets.md](./assets.md) | `assets` | Asset lifecycle rationale and code/test links |
| [market_data.md](./market_data.md) | `market_data` | Market data source rationale and fallback policy |
| [source-type-priority.md](./source-type-priority.md) | `source-type-priority` | Trust hierarchy rationale; priority should migrate to code/common |
| [confirmation-workflow.md](./confirmation-workflow.md) | `confirmation-workflow` | Review lifecycle rationale; state machine should migrate to code/common |
| [processing_account.md](./processing_account.md) | `processing_account` | In-transit funds model and proof references |
| [workflow-events.md](./workflow-events.md) | `workflow-events` | User-facing upload-to-report workflow event read model |
| [source-coverage-matrix.yaml](./source-coverage-matrix.yaml) | `source_coverage_matrix` | Machine-readable source-class coverage, proof levels, review requirements, and traceability targets |

## Proof Reports

| Report | Purpose |
|---|---|
| [critical-proof-matrix.yaml](./critical-proof-matrix.yaml) | Bidirectional README -> EPIC -> E2E macro outcome contract |
| `python tools/check_source_coverage_matrix.py` | Source-class coverage and proof-level contract |
| `python tools/analyze_test_ac_coverage.py --no-write --stdout` | Live local AC-to-test coverage report |
| [unified-coverage.json](https://github.com/wangzitian0/finance_report/blob/main/unified-coverage.json) | Current committed coverage baseline |

## Known Gaps

- Manual-verification ACs need automation or explicit manual-gate treatment. See
  [#454](https://github.com/wangzitian0/finance_report/issues/454).
- README/project metrics should be generated or validated. See
  [#455](https://github.com/wangzitian0/finance_report/issues/455).
- AC-to-EPIC mismatch triage is generated by
  `python tools/audit_ac_epic_mismatches.py`; use the live command or CI
  artifact instead of committing snapshot Markdown.

## Related

- [Root README](https://github.com/wangzitian0/finance_report/blob/main/README.md) — project fact entry point
- [Project vision](../target.md) — north-star goal, culture, and long-term direction
- [Project EPIC index](../project/README.md)
