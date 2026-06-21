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

That macro contract is a DERIVED (not committed) view of the one AC-keyed graph
([ac_graph.py](../../common/ssot/ac_graph.py)): its hand-curated outcome source
is [critical-proof-outcomes.yaml](./critical-proof-outcomes.yaml) and its proofs
come from the co-located `@ac_proof` decorators. It is validated by
`tools/check_ac_index.py` and gated for dangling/missing links by
`tools/check_ac_index.py`. The checker keeps the README outcome table, matrix
rows, owner EPIC declarations, and E2E proof anchors aligned.

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

## SSOT HLS Family Model

The high-level structure (HLS) family model groups the concepts in
[MANIFEST.yaml](./MANIFEST.yaml) into 6-8 reader-facing families so a domain
reader starts from a family entry point instead of a flat concept list. The
family model is a **definition layer only** — it routes readers and feeds the
`family` field; it does not own or re-own any concept (ownership stays in
MANIFEST.yaml).

- FR family map, concept/clause boundary, and governance loop:
  [EPIC-014 — SSOT HLS Family Model](../project/EPIC-014.ttd-transformation.md#ssot-hls-family-model).
- infra2 family map and boundary:
  [Infra-006 — SSOT HLS Family Model](../../repo/docs/project/Infra-006.documentation_engineering.md#ssot-hls-family-model).

Family/kind coverage is reported by `python tools/report_ssot_governance.py`
([#822](https://github.com/wangzitian0/finance_report/issues/822)). This model
is the foundation for the
[#824](https://github.com/wangzitian0/finance_report/issues/824) threshold
cleanup that backfills `family` / `kind` and binds child clauses.

## Core System Documents

| Document | Key | Current owner role |
|---|---|---|
| [development.md](./development.md) | `development` | Developer workflow and command entry points |
| [environments.md](./environments.md) | `environments` | Environment taxonomy and isolation rationale |
| [ci-cd.md](./ci-cd.md) | `ci-cd` / `ac_proof_execution_model` | CI gate semantics, workflow references, and AC-keyed proof execution placement |
| [ci-gate-inventory.yaml](./ci-gate-inventory.yaml) | `ci_gate_inventory` | MECE gate inventory and duplicate-cleanup candidate registry |
| [github-action-runtime.yaml](./github-action-runtime.yaml) | `github_action_runtime` | GitHub JavaScript action runtime inventory and Node20 metadata exceptions |
| [deployment.md](./deployment.md) | `deployment` | Deployment model and release rationale |
| [observability.md](./observability.md) | `observability` | Structured logging and SigNoz OTLP rationale |
| [runtime-incident-response.md](./runtime-incident-response.md) | `runtime_incident_response` | Runtime incident triage and stability-proof routing |
| [tdd.md](./tdd.md) | `tdd-transformation` | EPIC -> AC -> test workflow |
| [authority-tiers.md](./authority-tiers.md) | `authority_tiers` | AC authority tiers (PC/CP/HU/LP/PL) and the tier->valid-proof matrix |
| [coverage.md](./coverage.md) | `coverage` | Coverage metric semantics; code owner is `common/coverage/policy.py` |
| [auth.md](./auth.md) | `auth` | Auth architecture rationale and code references |
| [frontend-patterns.md](./frontend-patterns.md) | `frontend-patterns` | Frontend integration rules and proof references |
| [schema.md](./schema.md) | `schema` | Data-layer rationale and migration guardrails; mutable inventory is generated |
| [migration-risk.yaml](./migration-risk.yaml) | `migration_risk_classification` | Alembic migration risk levels and required release proof notes |
| [accounting.md](./accounting.md) | `accounting` | Double-entry rationale and invariant references |
| [package-model.md](./package-model.md) | `package_model` | Package = DDD bounded context; PackageContract + role model; governance computed from contracts |
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
| [extraction-audit-failed-cases.yaml](./extraction-audit-failed-cases.yaml) | [`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml) | Machine-readable audit-failed parsing case registry and parser-expansion boundary |
| [source-coverage-matrix.yaml](./source-coverage-matrix.yaml) | [`source_coverage_matrix`](./source-coverage-matrix.yaml) | Machine-readable source-class coverage, proof levels, review requirements, and traceability targets |

## Proof Reports

| Report | Purpose |
|---|---|
| [Generated API Reference](../reference/api.md) | OpenAPI-derived endpoint inventory |
| [Generated DB Schema Reference](../reference/db-schema.md) | SQLAlchemy-derived table, column, enum, index, constraint, and FK inventory |
| `python tools/check_ac_index.py` | Bidirectional README -> EPIC -> E2E macro outcome contract, a derived view of [critical-proof-outcomes.yaml](./critical-proof-outcomes.yaml) + `@ac_proof` decorators (rendered on demand by `tools/generate_critical_proof_matrix.py`, never committed) |
| `python tools/check_ac_index.py` | One consistency gate over the AC-keyed graph: no dangling `@ac_proof`, vision item, or macro outcome; every mandatory active AC has a real test reference |
| `python tools/check_source_coverage_matrix.py` | Source-class coverage and proof-level contract for [`source_coverage_matrix`](./source-coverage-matrix.yaml) |
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
