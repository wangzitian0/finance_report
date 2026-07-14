# EPIC-014: Test-Driven Documentation (TTD) Transformation

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1719): TTD philosophy + SSOT HLS governance design
     doc; its clauses are proven by tests/tooling doc-governance gates, not
     EPIC AC rows. -->

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, generated reports, and executable checks.
> **Vision Anchor**: `decision-filter-accuracy-auditability`
> **Phase**: Tooling Enhancement (Phase 3-5)
> **Duration**: 3-4 weeks
> **Owner**: Development Team
>
> **2026-05-25 alignment note**: Current proof metrics are owned by generated
> reports and executable checks; the root [README](https://github.com/wangzitian0/finance_report/blob/main/README.md) links to
> those sources instead of duplicating mutable values. This EPIC owns the TTD
> transformation scope; code/test migration follow-ups are tracked by issues
> #452, #453, #454, #455, and #456.
>
> **2026-06-12 simplification alignment**: The next TTD simplification target is
> macro domain documentation plus generated MkDocs references plus code/CI
> gates. Domain docs explain scope, concepts, invariants, and ownership; mutable
> API, DB, config, status, and proof inventories should be generated or
> mechanically validated. The umbrella issue is
> [#453](https://github.com/wangzitian0/finance_report/issues/453).

## 📌 Executive Summary

Transform the project's documentation approach from **prescriptive** (MUST/REQUIRE statements) to **descriptive** (design principles + automated enforcement). The goal is to make **tests and tools the single source of truth** for constraints, while documentation focuses on **why** and **how** rather than **what is mandatory**.

### Core Philosophy

| Old Approach (Prescriptive) | New Approach (TTD) |
|---------------------------|-------------------|
| Documentation says "MUST do X" | Tests fail if X is not done |
| SOP is a checklist document | SOP is an automated tool |
| "What to do" in prose | "What to do" in automated checks |
| Manual verification required | CI enforces rules automatically |
| Documentation drift possible | Tests = truth, docs = guidance |

## 🎯 Success Criteria

### Must Have (P0)
- [x] All `MUST`/`REQUIRE` statements removed from documentation
- [x] All constraint references point to tests (e.g., `See: tests/accounting/test_decimal_safety.py`)
- [x] Every SOP has at least one automated tool backing it
- [x] Pre-commit hooks enforce all static constraints
- [x] CI pipeline enforces all runtime constraints
- [x] No manual checklist processes remaining

### Nice to Have (P1)
- [ ] Interactive tool guide for new developers (`make help` covers 90%)
- [ ] Automated PR checks for documentation-test alignment
- [ ] SOP tools have `--dry-run` mode for preview
- [ ] Documentation includes "Why this constraint exists" sections

### Not Acceptable
- [ ] Constraints enforced only by documentation prose
- [ ] SOP is a markdown checklist without automation
- [ ] Test failures without corresponding documentation references
- [ ] Manual verification required for common operations

---

## Current Scope Ownership

This EPIC owns the TTD transformation principle: prose explains rationale, while
constraints are enforced by tools, tests, and CI. The detailed historical gap
analysis, phase plans, and per-tool completion tables were removed because they
were snapshots, not current truth.

| Fact | Owner |
|---|---|
| Mandatory work order and agent workflow | [orchestration.md](../agents/orchestration.md), [tdd.md](../../common/testing/tdd.md) |
| Security and engineering red lines | [red-lines.md](../agents/red-lines.md), executable guardrail tests |
| AC registry generation and orphan/stub checks | `tools/generate_ac_registry.py`, `tools/lint_doc_consistency.py` |
| AC proof quality | `tools/check_ac_index.py`, CI traceability artifact |
| Coverage policy | [coverage.md](../../common/testing/coverage.md), `common/meta/extension/coverage/policy.py` |
| Development and SOP commands | [development.md](../../common/meta/development.md), `make`, `moon`, and `tools/` entry points |

Historical details remain available in git history and removed-archive issue
[#548](https://github.com/wangzitian0/finance_report/issues/548). New TTD work
must add or update ACs, tests, and SSOT links instead of adding standalone
checklists.

## SSOT HLS Governance Loop

This high-level structure (HLS) roadmap is a design roadmap, not a proof source.
GitHub issues, generated reports, and CI gates own live status.

As-is:

- SSOT documents and `docs/ssot/MANIFEST.yaml` define ownership, but the
  family/concept/clause design model is still implicit.
- Some child parameters, machine tables, and baselines can be reviewed as if
  they were independent SSOT concepts instead of bound clauses or artifacts.
- FR application semantics and infra2 platform semantics are related, but the
  cross-system authority boundary is not measured.

To-be:

- [x] Define the FR SSOT HLS model with 6-8 families, concept boundaries, and
  child binding rules in
  [#821](https://github.com/wangzitian0/finance_report/issues/821) (see
  [SSOT HLS Family Model](#ssot-hls-family-model) below; documentation only —
  no concept is moved or re-owned in this step).
- [x] Add report-only design metrics for family coverage, orphan files,
  duplicate owners, clause binding, proof/checker coverage, and high-risk
  owner coverage in
  [#822](https://github.com/wangzitian0/finance_report/issues/822).
- [x] Promote only incremental and high-risk findings into CI gates once the
  metrics baseline is visible in
  [#823](https://github.com/wangzitian0/finance_report/issues/823).
- [ ] Run threshold-based SSOT cleanup only after the metrics show enough
  evidence for targeted consolidation in
  [#824](https://github.com/wangzitian0/finance_report/issues/824).
  - Each cleanup is selected from `python tools/report_ssot_governance.py` (not
    subjective review) and names the metric threshold it reduces:
    - AC-meta.ssot-governance.4 (AC14.1.14 removed, canonical id moved to `common/meta/contract.py`) reduces `finance_report.orphan_ssot_files` to zero.
    - AC-meta.ssot-governance.5 (AC14.1.15 removed, canonical id moved to `common/meta/contract.py`) keeps `finance_report.machine_owner_entries_missing_proof` at
      zero.
    - AC-meta.ssot-governance.8 (AC14.1.23 removed, canonical id moved to `common/meta/contract.py`) reduces `finance_report.high_risk_entries_missing_proof` from
      `2` to zero by binding the flagged high-risk `platform` concepts
      (`container_naming`, `test_optimization`) to their existing proof tests.
      Metadata-only backfill (`family` / `kind` / `proofs`); no concept is moved
      or re-owned and no runtime behavior changes.

## SSOT HLS Family Model

This is the FR high-level structure (HLS) family model defined by
[#821](https://github.com/wangzitian0/finance_report/issues/821). It is the
**foundation for the [#824](https://github.com/wangzitian0/finance_report/issues/824)
threshold cleanup**: it groups the existing FR SSOT concepts in
[`docs/ssot/MANIFEST.yaml`](../ssot/MANIFEST.yaml) into 6-8 reader-facing
families so cleanup PRs can backfill `family` / `kind` and bind child artifacts
deterministically.

This step is **documentation only**. It does not move, rename, merge, or
re-own any concept; `MANIFEST.yaml` remains the single owner registry. The
family column maps to the `family` field a manifest entry should carry; the
member column lists the current inferred manifest groupings (the
`inferred_family_distribution` keys in
`python tools/report_ssot_governance.py`) that belong to each family.

### Concept vs clause boundary

- A **concept** is an independently governed SSOT base element with its own
  owner file (an entry whose `kind` is `concept`, or unset and treated as the
  default). It is the unit that a family groups.
- A **clause** is a child parameter, machine table, baseline, registry, or
  matrix that only exists to parameterize a parent concept (`kind` of `clause`,
  `matrix`, `registry`, or `baseline`). A clause MUST `parent` its concept and
  inherit the parent's family; it is never reviewed as a standalone concept.
- A **family** is a reader-facing grouping of related concepts. Families do not
  own facts; they route a reader to the owning concept before the individual
  entry. Ownership stays in `MANIFEST.yaml`.

### FR family map (6-8 families)

| Family | Scope | Member manifest groups (inferred) |
|---|---|---|
| `accounting` | Double-entry ledger, in-transit funds, reconciliation, and trust hierarchy | `accounting`, `reconciliation`, `confirmation`, `processing`, `source` |
| `reporting` | Reports, frameworks, market data, assets, and evidence/workflow read models | `reporting`, `framework`, `market`, `assets`, `evidence`, `workflow` |
| `extraction` | Statement parsing, AI advisor, LLM provider abstraction, and PDF fixtures | `extraction`, `ai`, `llm`, `pdf` |
| `schema` | Database schema, data layering, enum naming, and migration risk | `schema`, `migration` |
| `platform` | Dev workflow, environments, CI/CD, coverage, deployment, and observability | `platform`, `development`, `environments`, `ci`, `test`, `delivery`, `coverage`, `deployment`, `observability`, `runtime`, `env` |
| `identity` | Auth identity and frontend integration contract | `auth`, `frontend` |
| `governance` | TDD workflow, critical-proof matrix, agent governance, and branch policy | `tdd`, `critical`, `agents`, `contributing` |

## Simplification Acceleration Track

This track narrows the next documentation pass to reducing reader load and
maintenance surface. It does not replace the EPIC -> AC -> test workflow; each
implementation PR still adds or updates ACs and focused checks for the behavior
it changes.

The target documentation shape is:

```text
macro domain doc -> generated MkDocs reference -> code/tool/CI gate
```

### Reader-load goals

- A domain reader should start from one family entry point, not a flat list of
  dozens of SSOT concepts.
- Domain docs should explain scope, core concepts, invariants, lifecycle/state
  machine, ownership boundary, generated references, and proof links.
- Endpoint lists, field definitions, DB table/enum inventories, environment key
  lists, status metrics, and CI/proof matrices should not be hand-maintained in
  prose when code, config, registries, or workflows can generate or validate
  them.
- The heaviest SSOT docs should shrink by replacing copied fact inventories with
  generated-reference links. The first pass targets `schema.md`, `ci-cd.md`,
  `development.md`, `observability.md`, and `deployment.md`.

### Workstreams

| Workstream | Tracking | Next action |
|---|---|---|
| HLS domain map | [#821](https://github.com/wangzitian0/finance_report/issues/821) | Define 6-8 families and backfill `family` / `kind` for manifest entries that still inherit `unknown` shape. |
| Generated contracts | [#453](https://github.com/wangzitian0/finance_report/issues/453) | Add generated DB schema and configuration references beside the existing generated API reference. |
| Project/status generation | [#455](https://github.com/wangzitian0/finance_report/issues/455) | Keep README/project status and proof metrics generated or validated instead of copied into prose. |
| Threshold cleanup | [#824](https://github.com/wangzitian0/finance_report/issues/824) | Use governance metrics and document-size hotspots to select narrow cleanup PRs. |
| Gates | [#823](https://github.com/wangzitian0/finance_report/issues/823) | Extend existing incremental gates when a new generated reference or code-owned contract is introduced. |

### First generated-reference candidates

| Reference | Source owner | Primary consumers |
|---|---|---|
| Existing generated API reference | FastAPI OpenAPI and backend schemas | Auth, extraction, reconciliation, reporting, workflow, asset, market-data docs |
| DB schema reference | SQLAlchemy metadata, Alembic metadata, and only non-derived layer/governance metadata | `schema.md` and domain docs that currently copy table or enum details |
| Configuration reference | Backend settings, frontend env usage, `.env.example`, Vault templates, and scope classification | `development.md`, `deployment.md`, `observability.md`, `ci-cd.md`, environment smoke docs |

### Completion signal

The simplification pass is effective when:

- `docs/ssot/README.md` routes readers by family before individual concept.
- Generated references are visible in MkDocs navigation and checked by CI or a
  build-time generator.
- The highest-load SSOT docs no longer copy mutable endpoint, env, DB, enum, or
  status inventories.
- Governance metrics show improved family/kind coverage and no new high-risk
  owner without proof.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [AGENTS.md](https://github.com/wangzitian0/finance_report/blob/main/AGENTS.md) — repository-wide agent and contributor entry point.
- [./AUDITS.md](./AUDITS.md) — audit index and retired standalone report notes.
- [./AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) — historical consistency audit snapshot.
- [./DECISIONS.md](./DECISIONS.md) — project decision log.
- [../ssot/tdd.md](../../common/testing/tdd.md) — canonical EPIC -> AC -> test workflow.
- [../agents/orchestration.md](../agents/orchestration.md) — agent workflow governance.
- [../agents/red-lines.md](../agents/red-lines.md) — security and engineering hard stops.
- [../contributing/branch-policy.md](../contributing/branch-policy.md) — branch and PR workflow.
- [Copilot instructions](https://github.com/wangzitian0/finance_report/blob/main/.github/copilot-instructions.md) — Copilot-specific contributor instructions.
- [frontend instructions](https://github.com/wangzitian0/finance_report/blob/main/.github/instructions/frontend.instructions.md) — frontend assistant instructions.
- [Python instructions](https://github.com/wangzitian0/finance_report/blob/main/.github/instructions/python.instructions.md) — Python assistant instructions.
- [PR template](https://github.com/wangzitian0/finance_report/blob/main/.github/pull_request_template.md) — PR description contract.
- [Backend tests README](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/tests/README.md) — test-suite organization, jointly owned with EPIC-008.

## Active TTD Operating Model

Current SOP coverage is intentionally tool-owned:

| Area | Tool or doc owner |
|---|---|
| Development setup | `make install`, `moon run :dev`, [development.md](../../common/meta/development.md) |
| Code quality | pre-commit, Ruff, mypy, CI lint |
| Testing and coverage | `moon run :test`, [coverage.md](../../common/testing/coverage.md), coverage tooling |
| Environment consistency | `tools/check_env_keys.py`, schema validation tooling |
| Deployment and smoke checks | [deployment.md](../../common/runtime/deployment.md), [ci-cd.md](../../common/testing/ci-cd.md), `tools/smoke_test.sh` |
| Project/AC traceability | registry generation, AC traceability, E2E EPIC traceability |

Do not use this EPIC as a live progress dashboard. Current counts, CI state,
issue state, and tool behavior must be read from generated reports, GitHub,
workflow artifacts, code, tests, or SSOT files.

## Historical Notes

Historical work-progress reports and test-organization audits were removed from this EPIC. Current TTD scope is defined by the objective, SSOT links, and the AC table below; live proof is owned by generated registries and executable checks.

---

## AC14.1: Coverage Enforcement Tooling — migrated to the `meta` package

> **The 23 AC14.1.* rows of this group are no longer defined here.** They
> migrated (migration closeout wave 2, #1663) into
> [`common/meta/contract.py`](../../common/meta/contract.py)'s `roadmap`,
> split by topic into `AC-meta.foundation-tooling.*`, `AC-meta.registry.*`,
> `AC-meta.doc-consistency.*`, `AC-meta.ssot-governance.*`,
> `AC-meta.issue-templates.*`, `AC-meta.generated-refs.*`, and
> `AC-meta.coverage-tiers.*` (the leading "14" is dropped; the original
> `AC14.1.n` id is kept as a trailing comment on each migrated record).
> `common/meta/extension/generate_ac_registry.py` reads package-contract
> roadmaps additively, so the AC index counts them without an EPIC-table
> mirror. This note references the ids for traceability but defines none of
> them — the contract is the single definition source.
