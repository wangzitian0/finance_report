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
([ac_graph.py](../../common/testing/ac_graph.py)): its hand-curated outcome source
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
| [ci-gate-inventory.yaml](./ci-gate-inventory.yaml) | `ci_gate_inventory` | Transitional stage/task_category job inventory and duplicate-cleanup candidate registry |
| [github-action-runtime.yaml](./github-action-runtime.yaml) | `github_action_runtime` | GitHub JavaScript action runtime inventory and Node20 metadata exceptions |
| [deployment.md](./deployment.md) | `deployment` | Deployment model and release rationale |
| [observability.md](./observability.md) | `observability` | Structured logging and OTLP rationale |
| [runtime-incident-response.md](./runtime-incident-response.md) | `runtime_incident_response` | Runtime incident triage and stability-proof routing |
| [tdd.md](./tdd.md) | `tdd-transformation` | EPIC -> AC -> test workflow |
| [common/meta/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/meta/readme.md) | `authority_tiers` | AC authority tiers (CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY) and the tier->valid-proof matrix — folded into the `meta` package (migration-standard step 3) |
| [coverage.md](./coverage.md) | `coverage` | Coverage metric semantics; code owner is `common/meta/extension/coverage/policy.py` |
| [frontend-patterns.md](./frontend-patterns.md) | `frontend-patterns` | Frontend integration rules and proof references (incl. browser auth/session) |
| [schema.md](./schema.md) | `schema` | Data-layer rationale and migration guardrails; mutable inventory is generated |
| [migration-risk.yaml](./migration-risk.yaml) | `migration_risk_classification` | Alembic migration risk levels and required release proof notes |
| [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) | `accounting` | Double-entry rationale and invariant references — internalized into the `ledger` package (migration-standard step 3) |
| [../../common/meta/readme.md](../../common/meta/readme.md) | `package_model` | Package = DDD bounded context; PackageContract + role model; governance computed from contracts. Self-hosted in the `common/meta` meta package. |
| [MANIFEST.yaml](./MANIFEST.yaml) | `manifest` | Machine-readable concept owner registry |

## Feature Documents

| Document | Key | Current owner role |
|---|---|---|
| [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) | `extraction` | Statement parsing rationale and code/test links — internalized into the `extraction` package (migration-standard step 3) |
| [common/testing/README.md#pdf-fixtures](https://github.com/wangzitian0/finance_report/blob/main/common/testing/README.md#pdf-fixtures) | `pdf_fixtures` | Synthetic PDF fixture commands, local-only input policy, and font fallback — internalized into the `testing` package (migration-standard step 3) |
| [reconciliation.md](./reconciliation.md) | `reconciliation` | **Migrated** (wave 3, #1664) — pointer stub; owner is [`common/reconciliation/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/reconciliation/readme.md) |
| [reporting.md](./reporting.md) | `reporting` | **Migrated** (wave 3, #1664) — pointer stub; owner is [`common/reporting/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/reporting/readme.md) |
| [framework-reporting.md](./framework-reporting.md) | `framework_reporting` | US/HK target-backward policy layer for personal report packages — future `reporting`-package candidate, not yet internalized |
| [ai.md](./ai.md) | `ai` | **Migrated** (wave 3, #1664) — pointer stub; owner is [`common/advisor/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/advisor/readme.md) |
| [assets.md](./assets.md) | `assets` | **Migrated** (wave 3, #1664) — pointer stub; owners are [`common/portfolio/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/portfolio/readme.md) (position math, #1422) and [`common/pricing/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/pricing/readme.md) (manual valuation, #1610) |
| [market_data.md](./market_data.md) | `market_data` | **Migrated** (wave 3, #1664) — pointer stub; owner is [`common/pricing/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/pricing/readme.md) |
| [source-type-priority.md](./source-type-priority.md) | `source-type-priority` | **Migrated** (wave 3, #1664) — pointer stub; owner is [`common/audit/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/audit/readme.md) |
| [confirmation-workflow.md](./confirmation-workflow.md) | `confirmation-workflow` | Review lifecycle rationale; state machine should migrate to code/common |
| [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) | `processing_account` | In-transit funds model and proof references — internalized into the `ledger` package (migration-standard step 3) |
| [workflow-events.md](./workflow-events.md) | `workflow-events` | User-facing upload-to-report workflow event read model |
| [common/extraction/audit-failed-cases.yaml](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/audit-failed-cases.yaml) | [`extraction_failed_case_registry`](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/audit-failed-cases.yaml) | Machine-readable audit-failed parsing case registry and parser-expansion boundary — internalized into the `extraction` package |
| [source-coverage-matrix.yaml](./source-coverage-matrix.yaml) | [`source_coverage_matrix`](./source-coverage-matrix.yaml) | Machine-readable source-class coverage, proof levels, review requirements, and traceability targets |

## Cross-Cutting Classification (migration closeout wave 3, #1664)

Every remaining `docs/ssot/*.md` domain doc is now explicitly classified —
either genuinely horizontal (no single package owns it) or a real future
package-internalization candidate not yet done. This satisfies the
"internalize into the owning package, or explicitly classify as
cross-cutting with a recorded owner" requirement without silently leaving
docs unclassified. A "candidate" row is **not** internalized yet — do not
read it as done.

| Document | Classification | Recorded owner |
|---|---|---|
| [ci-cd.md](./ci-cd.md) | Horizontal infra | Repo-wide CI/CD pipeline; no single package owns workflow structure |
| [deployment.md](./deployment.md) | Horizontal infra | Repo-wide Dokploy/VPS deployment model; no single package |
| [development.md](./development.md) | Horizontal infra | Repo-wide dev workflow / moon commands / toolchain; no single package |
| [environments.md](./environments.md) | Horizontal infra | Repo-wide environment taxonomy and isolation; no single package |
| [tdd.md](./tdd.md) | Horizontal infra | EPIC→AC→test workflow methodology; `meta` governs *form*, but this doc is process narrative, not a `meta` contract fact |
| [coverage.md](./coverage.md) | Already code-owned | `common/testing/coverage/policy.py` is the fact owner; this doc is rationale-only (correctly modeled — no action needed) |
| [schema.md](./schema.md) | Deferred | Fate is an **explicit open decision from #1420** (ledger decoupling: money/value → Shared-Kernel out of ledger) — not resolved by this pass |
| [frontend-patterns.md](./frontend-patterns.md) | Horizontal infra | Spans every package's frontend implementation (raw-fetch ban, auth/session); no single package owner |
| [observability.md](./observability.md), [observability-logging.md](./observability-logging.md) | Future package candidate | Natural owner is [`common/observability/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/observability/readme.md) — not yet internalized |
| [runtime-incident-response.md](./runtime-incident-response.md) | Horizontal infra | Ops runbook spanning all packages; references `observability` for query patterns but isn't owned by it |
| [workflow-events.md](./workflow-events.md) | Future package candidate | Natural owner is [`common/platform/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/platform/readme.md) (event bus / outbox) — not yet internalized |
| [evidence-lineage.md](./evidence-lineage.md) | Horizontal infra (for now) | Spans `extraction`/`reconciliation`/`reporting` traceability; no single owner without a cross-package graph package |
| [confirmation-workflow.md](./confirmation-workflow.md) | Future package candidate | Natural owner is [`common/extraction/readme.md`](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) (statement review lifecycle) — not yet internalized |
| [env-reference.generated.md](./env-reference.generated.md) | Generated | Machine-generated by `tools/generate_env_reference.py`; not hand-owned |

`source-type-priority.md` was migrated during this same pass (see the
Feature Documents table above) once its implementation was traced to
`apps/backend/src/audit/source_type_priority.py` — the physical location
made `audit` the correct owner rather than the `extraction` guess above.

## Gate Data Directory (migration closeout wave 3, #1664, Part B)

**Decision: `docs/ssot/` stays the gate-data directory.** All 13 yaml/json
gate-input files (`ac-score-baseline.jsonl`, `ac-tier-baseline.json`,
`app-boundary-baseline.json`, `protection-floor.json`,
`critical-proof-outcomes.yaml`, `source-coverage-matrix.yaml`,
`migration-risk.yaml`, `draft-package-baseline.json`,
`governance-exceptions.yaml`, `github-action-runtime.yaml`,
`ci-gate-inventory.yaml`, `delivery-gates.yaml`,
`test-execution-matrix.yaml`) stay in place rather than moving into
`common/meta/data/` or an owning package's `data/` layer.

One of them (`ci-gate-inventory.yaml`) also follows a **cross-repo shared
convention**: the sibling `repo/` submodule keeps its own, separate
`repo/docs/ssot/ci-gate-inventory.yaml` at the identical relative path,
validated by its own `repo/tools/ci_gate_audit.py` against the same schema
(`repo/docs/project/Infra-016.ci_gate_inventory.md`). The two files are
independent (not cross-read), but relocating this repo's copy off
`docs/ssot/<name>` would break the shared-path convention the two repos rely
on to stay comparable — a cross-repo coordination change, not a
single-repo doc cleanup, and explicitly out of scope for this PR.

The other 11 are heavily read by `tests/tooling/` and `tools/` gate scripts
by their current path; a move would require updating every consumer in the
same PR with no test coverage gap, which is a large, high-blast-radius
change for a documentation-cleanup PR to carry. `meta`'s data layer becoming
the *computed* index (Part C of #1664) is the point at which physically
relocating these makes sense — retiring `MANIFEST.yaml`/the registry and
moving the gate-data files are the same cutover, not two.

**Three more ratchet baselines follow the identical decision**, though they
postdate the original 13-file enumeration above: `fk-cascade-baseline.json`
(cross-domain FK-cascade shrink-only ratchet, read by
`tests/tooling/test_fk_cascade_ratchet.py`), `delivery-layer-baseline.json`
(app-delivery-layer line-count ratchet, `AC-meta.delivery.1`, read by
`tests/tooling/test_delivery_layer_ratchet.py`), and
[epic-residue-baseline.json](./epic-residue-baseline.json) (EPIC AC residue
census, `AC-meta.residue.1`, referenced below). Same reasoning, same
decision: they stay in `docs/ssot/` by name-hardcoded consumer path.

## AC Index Is Computed (migration closeout, #1719 — #1664 Part C status)

Since #1719 the **AC index is fully computed** by
[`common/meta/extension/generate_ac_registry.py`](../../common/meta/extension/generate_ac_registry.py)
(meta's extension layer) from exactly two sources:

1. **Package contract roadmaps** (`common/<pkg>/contract.py`) — the
   authoritative source; on any id collision the roadmap record wins.
2. **Explicitly marked EPIC residue rows** (`<!-- epic-owned: ... -->`,
   ratcheted by [epic-residue-baseline.json](./epic-residue-baseline.json)) —
   EPIC markdown is no longer an authoritative source for any migrated AC.

`docs/ac_registry.yaml` / `docs/infra_registry.yaml` are checked-in **index
stubs only** (`generated_from_epics: true` triggers materialization on load);
`docs/ac_registry_overrides.yaml` is empty. That completes the "reduced to
generated artifacts of meta's data layer" half of #1664 Part C.

## MANIFEST.yaml Status (migration closeout wave 3, #1664 Part C — final)

The other half of Part C — retiring `MANIFEST.yaml` + `tools/check_manifest.py`
+ `check_ssot_ownership` in favor of a fully **computed** concept-ownership
index (the same "governance computed, not authored" principle the AC index
above now follows) — turned out to be the same class of cutover as the
gate-data relocation: high blast-radius for a single PR. #1664 closed it out
to the safely-deliverable half instead of forcing a risky rewrite:

1. **Accuracy audit (done)** — every one of MANIFEST's 76 concepts was
   checked against its owner: the 27 `common/<pkg>`-owned concepts all
   correctly point at their post-migration package readme (Part A); the 46
   `docs/ssot/`-owned concepts are all genuinely cross-cutting infra, live
   gate data, or generated (classified in the tables above); the remaining
   3 are governance docs outside both `docs/ssot/` and `common/`
   (`docs/agents/red-lines.md`, `docs/agents/orchestration.md`,
   `docs/contributing/branch-policy.md`). No stale owner found.
2. **New anti-drift gate (done)** — `AC-meta.manifest.1`
   (`common/meta/extension/check_manifest.py`, check5,
   `check_docs_ssot_files_classified`): every file physically present in
   `docs/ssot/` must be referenced by name somewhere in this README. A file
   dropped into `docs/ssot/` without being classified here now fails CI —
   this is what caught `fk-cascade-baseline.json` /
   `delivery-layer-baseline.json` missing from the Gate Data Directory
   section above during #1664 itself.
3. **Full computed-index rewrite (deferred)** — filed as
   [#1799](https://github.com/wangzitian0/finance_report/issues/1799).
   `common/meta/data/projection.py` (meta's existing computed-index layer)
   has no structured "concepts" field on `PackageContract` to project from
   yet; adding one touches ~20 package contracts, and the ~49
   no-package-owner concepts (cross-cutting/gate-data/generated) need a
   residual-manifest idiom mirroring the EPIC residue markers below rather
   than disappearing outright. Per umbrella #1416's 2026-07-12 scope-freeze
   rule, #1799 is explicitly a post-migration backlog item, not part of the
   frozen child set — MANIFEST.yaml is accurate and gated today, so this is
   architecture debt, not a correctness gap.
4. **CLAUDE.md navigation (done)** — updated in the same PR (explicit user
   authorization for this task lifted the file's edit prohibition) to
   describe the post-migration reality: domain concepts live in package
   readmes, `docs/ssot/` holds cross-cutting infra docs / gate data /
   generated artifacts, and `MANIFEST.yaml` is the ownership registry for
   both halves rather than a claim that `docs/ssot/` itself is the source.

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
