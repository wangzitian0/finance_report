# EPIC-014: Test-Driven Documentation (TTD) Transformation

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
| Mandatory work order and agent workflow | [orchestration.md](../agents/orchestration.md), [tdd.md](../ssot/tdd.md) |
| Security and engineering red lines | [red-lines.md](../agents/red-lines.md), executable guardrail tests |
| AC registry generation and orphan/stub checks | `tools/generate_ac_registry.py`, `tools/lint_doc_consistency.py` |
| AC proof quality | `tools/check_ac_traceability.py`, CI traceability artifact |
| Coverage policy | [coverage.md](../ssot/coverage.md), `common/coverage/policy.py` |
| Development and SOP commands | [development.md](../ssot/development.md), `make`, `moon`, and `tools/` entry points |

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

- [ ] Define the FR SSOT HLS model with 6-8 families, concept boundaries, and
  child binding rules in
  [#821](https://github.com/wangzitian0/finance_report/issues/821).
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
- [../ssot/tdd.md](../ssot/tdd.md) — canonical EPIC -> AC -> test workflow.
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
| Development setup | `make install`, `moon run :dev`, [development.md](../ssot/development.md) |
| Code quality | pre-commit, Ruff, mypy, CI lint |
| Testing and coverage | `moon run :test`, [coverage.md](../ssot/coverage.md), coverage tooling |
| Environment consistency | `tools/check_env_keys.py`, schema validation tooling |
| Deployment and smoke checks | [deployment.md](../ssot/deployment.md), [ci-cd.md](../ssot/ci-cd.md), `tools/smoke_test.sh` |
| Project/AC traceability | registry generation, AC traceability, E2E EPIC traceability |

Do not use this EPIC as a live progress dashboard. Current counts, CI state,
issue state, and tool behavior must be read from generated reports, GitHub,
workflow artifacts, code, tests, or SSOT files.

## Historical Notes

Historical work-progress reports and test-organization audits were removed from this EPIC. Current TTD scope is defined by the objective, SSOT links, and the AC table below; live proof is owned by generated registries and executable checks.

---

## 🧪 Infra Test Cases (Coverage Enforcement)

> **Registry**: `docs/infra_registry.yaml`
> **Coverage**: See `apps/backend/tests/infra/`

### AC14.1: Coverage Enforcement Tooling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC14.1.1 | Backend coverage ≥ 90% enforced locally via `pyproject.toml` (CI uses `--cov-fail-under=0`; target: 99%; local pre-push enforcement threshold: 90%) | `test_coverage_threshold_enforced` | `infra/test_coverage_enforcement.py` | P0 |
| AC14.1.2 | Pre-commit mypy hook blocks type errors before commit | `test_mypy_precommit_blocks_type_errors` | `infra/test_precommit_hooks.py` | P0 |
| AC14.1.3 | validate_schemas.py exits non-zero when Pydantic fields lack Field() descriptions | `test_validate_schemas_fails_missing_desc` | `infra/test_validate_schemas.py` | P0 |
| AC14.1.4 | check_env_keys.py detects missing keys across secrets.ctmpl, config.py, .env.example | `test_env_keys_three_way_sync` | `infra/test_check_env_keys.py` | P0 |
| AC14.1.5 | smoke_test.sh runs successfully against local docker environment | `test_smoke_test_local_pass` | `infra/test_smoke_test.py` | P1 |
| AC14.1.6 | generate_ac_registry.py produces zero ghost ACs and zero overlap between feature and infra registries | `test_ac_registry_no_ghost_no_overlap` | `tests/tooling/test_issue_493_foundation_ttd_behavior.py` | P1 |
| AC14.1.7 | Generated analysis snapshots are not checked into `docs/analysis/`; live coverage and mismatch data come from tools or CI artifacts | `test_AC14_1_7_generated_analysis_snapshots_are_absent` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC14.1.8 | Reconciliation threshold prose points to code/config owners instead of claiming Markdown is the single authority | `test_AC14_1_8_reconciliation_thresholds_are_code_owned` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC14.1.9 | SSOT manifest `#anchor` owners and cross-references resolve to actual Markdown anchors | `test_AC14_1_9_manifest_anchor_refs_must_exist` | `tests/tooling/test_check_manifest.py` | P0 |
| AC14.1.10 | Frontend source cannot call raw `fetch()` outside `apps/frontend/src/lib/api.ts` | `test_AC14_1_10_frontend_raw_fetch_is_limited_to_api_wrapper` | `tests/tooling/test_lint_doc_consistency.py` | P0 |
| AC14.1.11 | GitHub issue templates require phenomenon, reproduction, minimal fix, rationale, and acceptance criteria sections with valid repository labels | `test_AC14_1_11_issue_templates_require_diagnostic_fix_and_acceptance_sections` | `tests/tooling/test_issue_template_contract.py` | P1 |
| AC14.1.12 | SSOT governance metrics report finance_report and infra2 manifest shape, proof coverage, and future gate candidates without blocking CI | `test_AC14_1_12_report_covers_finance_and_infra2_manifest_shapes` | `tests/tooling/test_ssot_governance_report.py` | P1 |
| AC14.1.13 | SSOT governance gates block changed-file and changed-manifest-entry debt, explain #823/HLS ownership, and support issue-linked temporary exceptions | `test_AC14_1_13_incremental_gate_only_blocks_changed_ssot_debt` | `tests/tooling/test_ssot_governance_report.py` | P1 |
| AC14.1.14 | Threshold cleanup for #824 reduces `finance_report.orphan_ssot_files` to zero by binding orphan SSOT files to parent concepts without runtime behavior changes | `test_AC14_1_14_finance_report_orphan_ssot_files_are_manifest_owned` | `tests/tooling/test_ssot_governance_report.py` | P1 |
| AC14.1.15 | Threshold cleanup for #824 migrates representative machine-owned FR SSOT entries to explicit `family`, `kind`, `proofs`, and inbound SSOT Markdown links so `finance_report.machine_owner_entries_missing_proof` stays zero | `test_AC14_1_15_machine_owned_ssot_entries_have_explicit_shape_and_proof` | `tests/tooling/test_ssot_governance_report.py` | P1 |
| AC14.1.16 | SSOT governance gates keep protected per-system governance ratios non-decreasing and protected debt counts non-increasing against the base ref | `test_AC14_1_16_ssot_governance_ratios_cannot_regress` | `tests/tooling/test_ssot_governance_report.py` | P1 |
| AC14.1.17 | DB schema inventory is generated from SQLAlchemy metadata, published by the MkDocs build, CI-checked for deterministic generation, gitignored as generated output, and linked from macro SSOT/domain docs instead of hand-maintained table/column/API catalogs | `test_AC14_1_17_render_db_schema_reference_uses_sqlalchemy_metadata`, `test_AC14_1_17_generated_db_schema_reference_is_ci_checked` | `tests/tooling/test_generate_db_schema_reference.py`, `tests/tooling/test_post_merge_e2e_gates.py` | P1 |
