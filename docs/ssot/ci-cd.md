# CI/CD and Test Optimization SSOT

> **SSOT Key**: `ci-cd`
> **Source of Truth** for CI job structure, test optimization modes, and performance metrics.

*Extracted from [development.md](./development.md) — see that file for Moon commands and local setup.*

---

## CI Job Structure

The GitHub Actions workflow (`.github/workflows/ci.yml`) follows this job dependency order:

```
standalone: lint ────────────────────────────────────────────────────────────────┐
standalone: ac-traceability ────────────────────────────────────────────────────┤
changes (classify-changes) ──→ backend shards ───────┐                          │
                         ├────→ schema-migrations ──────────────────────────────┤
                         ├────→ frontend ─────────────┼→ unified-coverage ───────┤
                         ├────→ tooling-coverage ─────┘                          │
                         ├────→ backend-integration ─────────────────────────────┤
                         ├────→ backend-e2e-tier1 ───────────────────────────────┤→ finish
                         └────→ container-images ────────────────────────────────┘
```

### Job Details

| Job | Purpose | Dependencies |
|-----|---------|--------------|
| **changes** | Detect whether changed paths require heavy backend/frontend/coverage jobs | None |
| **lint** | Static analysis (backend `src tests` ruff check + format check, frontend lint) + manifest/doc/CI metrics contract checks | None (first job) |
| **schema-migrations** | Run Alembic `upgrade head` followed by `alembic check` against an ephemeral Postgres service before merge | `needs: [changes]` |
| **backend** (Shards 1-6) | Backend fast-path tests only: `-m "not slow and not e2e and not integration"` | `needs: [changes]` |
| **backend-integration** | Backend integration stage (`-m "integration"`), deterministic service-backed behavior checks | `needs: [changes]` |
| **backend-e2e-tier1** | Backend Tier-1 API E2E stage (`apps/backend/tests/e2e/test_core_journeys.py` with `-m e2e`), executed with explicit marker override | `needs: [changes]` |
| **frontend** | Frontend build + Vitest + Playwright tests when heavy CI is required | `needs: [changes]` |
| **container-images** | Build backend and frontend staging images without pushing on PRs; push SHA-tagged images only on `main` | `needs: [changes]` |
| **tooling-coverage** | Run root tooling tests with common/tools coverage and upload LCOV inputs | `needs: [changes]` |
| **unified-coverage** | Merge backend, frontend, common, and tools LCOV inputs, audit source-tree/LCOV policy, calculate unified coverage, compare to baseline, update Coveralls when heavy CI is required | `needs: [changes, backend, frontend, tooling-coverage]` |
| **ac-traceability** | Verify AC-to-test traceability for all PR/main changes, including docs-only changes | None |
| **finish** | Aggregate all required and skipped job results | `needs: [changes, schema-migrations, backend, backend-integration, backend-e2e-tier1, frontend, container-images, lint, tooling-coverage, unified-coverage, ac-traceability]` |

### Key CI Properties

1. **Standalone Lint Job**: Runs independently; lint failures surface in ~1 min (not after 10 min backend shard).
2. **Change Classification**: Lightweight documentation, issue-template, markdown, and `.github/workflows/docs.yml` changes skip backend, frontend, and unified coverage. Runtime, test, tooling, CI, dependency, and coverage-policy changes run the full heavy path.
3. **Stable Required Checks**: Heavy jobs are skipped through job-level conditions rather than removing the workflow, so required check names remain visible and mergeable.
4. **AC Traceability Always Runs**: AC traceability is separate from unified coverage so docs-only AC/EPIC changes still get traceability validation. The job first runs `tools/generate_ac_registry.py --check` to ensure generated registry indexes can be materialized from EPIC docs plus explicit overrides, then runs `tools/check_ac_traceability.py` as the fail-closed gate, then runs `tools/check_e2e_epic_traceability.py` to ensure product E2E root test functions carry function-level EPIC IDs, every project EPIC has product E2E ownership, the README EPIC map matches project EPIC files, and unclassified E2E-like assets outside declared roots fail CI, then runs `tools/check_critical_proof_matrix.py` to validate the small core proof matrix, then generates `AC-TEST-TRACEABILITY-AUDIT.md` into `$RUNNER_TEMP`; the audit is uploaded as a CI artifact together with the critical proof matrix report. The job also runs `tools/reconciliation_audit.py` through the backend uv environment as a hard gate and uploads reconciliation audit JSON/Markdown with the same artifact. The audit distinguishes CI-executed real test references from `_ac_stubs`, trivial placeholder assertions, pure `pass`, pure skipped tests, and real references that live only in non-required execution stages. `docs/ssot/test-execution-matrix.yaml` owns the path-to-stage mapping. CI fails on mandatory AC coverage that is missing, placeholder-only, stub-only, or real-only outside CI-required stages; full-strikethrough deprecated ACs are excluded from the mandatory gate. The macro gate fails README/matrix/owner-EPIC drift, E2E/EPIC ownership drift, duplicate critical proof IDs, and broad/reference-only critical proof anchors. The generated audit is uploaded as a CI artifact; checked-in archive copies were retired to reduce merge conflicts.
5. **Schema migrations are PR merge authority**: `schema-migrations` starts after change classification for heavy PR/main changes and runs `uv run alembic upgrade head` followed by `uv run alembic check` against real ephemeral Postgres. This is the authoritative pre-merge proof that Alembic can build the production schema and that SQLAlchemy model changes do not drift from migrations. Preview and staging prove deployed runtime health only; they must not be the first place schema DDL correctness is discovered. The job uploads `schema-migration-test-context` with the migration log and repository/run metadata.
6. **Generated API reference is code-owned**: Static API reference docs are generated from FastAPI OpenAPI by `tools/generate_api_reference.py`. PR CI runs `python ../../tools/generate_api_reference.py --check` inside the backend uv environment after dependencies are installed, so endpoint paths, parameters, request schemas, response schemas, and enum values cannot drift into hand-written Markdown.
7. **Generated DB schema reference is code-owned**: Static DB schema docs are generated from SQLAlchemy model metadata by `tools/generate_db_schema_reference.py`. The generated page is intentionally gitignored and is materialized by the MkDocs build hook in `docs/hooks.py`. PR CI generates it inside the backend uv environment and then runs `python ../../tools/generate_db_schema_reference.py --check`, so table, column, enum, index, constraint, and foreign-key inventory stays code-owned instead of duplicated in prose.
8. **Backend stages are explicit and split**: Backend fast-path remains shard stage (`backend`) with `-m "not slow and not e2e and not integration"`. Standalone gates start immediately: `lint` and `ac-traceability` have no `needs` dependency and run in parallel with change classification. Deterministic test, schema migration, and image jobs start after change classification and do not wait for lint, AC traceability, or behavior-only backend gates. Behavior-only backend gates run in parallel as explicit `backend-integration` and `backend-e2e-tier1` stages, and finish remains the authoritative aggregate gate for lint, AC traceability, schema migrations, tests, image validation, coverage, and skipped heavy-job semantics.
9. **Coverage Debug Context Is Always Uploaded**: The `tooling-coverage` job uploads `coverage-tooling` with `coverage/common.lcov` and `coverage/tools.lcov`; the `unified-coverage` job downloads that artifact and uploads `unified-coverage-context` on success and failure. The unified artifact contains `coverage/backend.lcov`, `coverage/frontend.lcov`, `coverage/common.lcov`, `coverage/tools.lcov`, the current `unified-coverage.json`, and `coverage/coverage-context.txt` with raw line-count inputs, commit/event/run metadata, toolchain versions, and input hashes. Coverage regressions must be diagnosed from these artifacts before treating a percentage delta as nondeterminism.
10. **CI Observability Artifacts Are Failure-Path Owned**: Backend shard, backend integration, backend Tier-1 E2E, frontend Vitest, frontend Playwright, schema migrations, tooling/common coverage, AC traceability, PR preview, staging, manual AI/OCR, production release, and scheduled cleanup gates publish CI observability artifacts with `if: always()`. These artifacts include JUnit XML where pytest or Vitest/Playwright can produce it, raw coverage/report inputs where relevant, and a small context file with repository/event/ref/SHA/run metadata plus target environment/version fields. Step summaries remain human-readable status pages; artifacts are the replayable evidence for both success and failure.
11. **Coveralls Is Main-Only Reporting**: Pull requests do not call Coveralls and therefore do not publish external Coveralls status contexts. CI pass/fail is decided by local gates (`tools/check_ci_metrics_contract.py`, `tools/check_coverage_policy.py`, `tools/calculate_unified_coverage.py`) aggregated by `finish`. Main pushes upload only the unified line-only LCOV report to Coveralls for badge and trend reporting after the local coverage gate passes. Backend/frontend per-flag Coveralls uploads are intentionally absent so a single commit has one reporting denominator.
12. **Single CI Metrics Contract**: `tools/check_ci_metrics_contract.py` is the single CI metrics contract. It runs in `lint` and validates that source-root discovery, `common/coverage/policy.py`, workflow gates, and AC traceability semantics stay aligned before coverage jobs finish.
13. **Toolchain Contract**: `tools/check_toolchain_contract.py` runs in lint and fails when Python, Node.js, uv, Docker base images, Compose service images, or frontend engine constraints drift from `toolchain.toml`.
14. **PR Image Build Validation**: PR CI dry-runs staging image builds before merge with the same Dockerfiles, contexts, and build arguments used by `main`. Main push CI is the only path that pushes SHA-tagged images to GHCR.
15. **Coverage Policy Audit**: `tools/check_coverage_policy.py` fails CI if backend, frontend, common, or tools source files drift from their LCOV report.
16. **No-regression gate**: Zero-tolerance; if ANY component is below baseline, CI fails immediately.
17. **Deny-list coverage scope**: Coverage scope is deny-list based within each governed source root. CI recursively expects every eligible source file in backend, frontend, common, and tools LCOV unless `common/coverage/policy.py` explicitly excludes it. New source roots fail the metrics contract until added to the policy and report pipeline.

### Env x Stage Contract

This SSOT separates environment taxonomy, pipeline stages, and GitHub Actions jobs.
Environment taxonomy names the runtime contexts in [environments.md](./environments.md).
Pipeline stages are quality gates such as changed UT, lint/static checks, full UT,
integration, regression/E2E, image validation, deploy smoke, provider gates, and
release integrity. GitHub Actions jobs are implementation lanes for selected
environment/stage cells.

Local runs are fast advisory gates. PR CI is the deterministic merge authority.
PR Preview, staging, and production are deployed-environment proof gates. The model
is an Env x Stage Execution Matrix: not every environment runs every pipeline stage,
and environment names must not be counted as pipeline stages.

#### Environment Axis

| Environment | Meaning |
|---|---|
| `local` | Developer machine and local CI commands |
| `pr` | GitHub PR/main CI runner proof before merge or staging consumption |
| `pr-preview` | Per-PR deployed Docker environment |
| `staging` | Shared post-merge deployed environment for successful `main` SHAs |
| `prd` | Production release environment |

#### Pipeline Stage Axis

| Pipeline stage | Purpose |
|---|---|
| Changed/Affected UT | Fast local or focused unit feedback for touched/affected code |
| Lint/Static | Syntax, formatting, static contracts, SSOT and traceability checks |
| Full UT | Deterministic unit coverage over governed app/tooling source trees |
| Integration | Service-backed deterministic tests that do not require deployed routing |
| Regression/E2E | Deterministic API/browser/user-journey proof |
| Image Build | Dockerfile, build context, and build-argument proof |
| Deploy Smoke | Runtime health, routing, version, and deploy integrity proof |
| Provider Gate | Provider-backed OCR/LLM proof with real external credentials |
| Release Integrity | Manual production release prerequisite and image/deploy proof |

#### Env x Stage Execution Matrix

| Env \ Stage | Changed/Affected UT | Lint/Static | Full UT | Integration | Regression/E2E | Image Build | Deploy Smoke | Provider Gate | Release Integrity |
|---|---|---|---|---|---|---|---|---|---|
| `local` | default | focused/static contracts | risk-triggered only | risk-triggered only | not default | no | no | no | no |
| `pr` | covered by full gates | required | required for heavy changes | required for heavy changes | Tier-1/provider-free required for heavy changes | dry-run required for heavy changes | no | no | no |
| `pr-preview` | no | no | no | no | runtime/UI/API preview-relevant subset after successful PR CI | no PR images | runner `/api/health` + smoke/E2E | no | no |
| `staging` | no | no | no | no | merged-SHA non-LLM regression plus provider-backed regression when required | reuse or build missing SHA images | required | runs when real provider proof is required | no |
| `prd` | no | no | no | no | prod-safe smoke only | release image proof | required | no first-time proof | required |

Production release proof is intentionally narrow: production validates release
integrity and availability, not first-time deterministic business behavior.

### Path Risk to Local Gate Matrix

Default local verification starts with affected fast tests such as
`moon run :test -- --smart`, focused backend paths through
`moon run :test -- --fast tests/...`, focused Vitest/spec runs, or the smallest
relevant tooling contract. Direct backend `pytest tests/...` uses the backend
default coverage policy and is not the focused TDD path. Risk-triggered local
escalation applies when the changed path can affect behavior outside the touched
file.

| Changed path or concern | Default local gate | Escalation trigger |
|---|---|---|
| Ordinary backend source | `moon run :test -- --smart` or `moon run :test -- --fast tests/...` for a focused backend path | Escalate when the change crosses service boundaries or touches shared helpers |
| accounting, posting, reconciliation, money, balance | Focused domain pytest suite plus changed-file tests | Always include invariant tests beyond the touched file |
| schema, migrations | `cd apps/backend && uv run alembic upgrade head && uv run alembic check`, plus focused DB-backed tests | Required for any Alembic, SQLAlchemy model, enum, or persistence contract change |
| API contract, OpenAPI | Backend API tests plus affected frontend API consumer tests | Required for route, schema, generated API reference, or response-shape changes |
| Frontend component or route | Focused Vitest/spec, then affected Playwright when browser behavior changes | Escalate for navigation, responsive layout, workflow, or API-bound behavior |
| shared common/tooling | Focused tooling tests plus affected downstream contracts | Escalate when a common package feeds CI, coverage, SSOT, or command wrappers |
| Docker, workflow, environment, deploy | Static/tooling contract checks locally; PR CI and deployed gates own runtime proof | Required image/deploy proof stays in PR CI, PR Preview, staging, or production |
| docs-only | SSOT/doc/traceability checks only | Escalate only when docs change workflow, registry, AC, or proof semantics |

### Stage Matrix and Left-Move Guidance

| Stage | Current execution | Scope in CI | Coverage effect | Left-move action |
|---|---|---|---|---|
| Schema migrations | `schema-migrations` job after change classification | Alembic `upgrade head` and `check` against ephemeral Postgres | No line coverage effect | Keep as PR merge authority; preview/staging must only prove deployed runtime health |
| Unit (fast/shard) | `backend` job, 6 shards immediately after change classification | `-m "not slow and not e2e and not integration"` | Feeds unified line coverage (backend component) | Keep as deterministic base and expand shards if needed |
| Integration (backend marker) | `backend-integration` job (`-m "integration"`) | `apps/backend/tests/**/*` marker-scoped integration suites with service-backed env | Not part of unified line baseline yet | Add sharding when count growth justifies it; keep explicit marker gate in CI |
| Tooling/common contracts | `tooling-coverage` job | `tests/tooling/` with `--cov=common --cov=tools` | Feeds unified line coverage (common/tools components) | Keep parallel to app tests so tooling failures and LCOV inputs are independently visible |
| Tier 1 API E2E | `backend-e2e-tier1` job (`apps/backend/tests/e2e/test_core_journeys.py` with `-m "e2e"`) | Serial backend contract/HTTP/DB/S3 API behavioral paths with Postgres and MinIO bucket readiness | Behavioral proof only; AC traceability-backed | Stabilize a deterministic API subset first, then scale by marker or folder |
| Tier 2 HTTP E2E | PR/staging/prod HTTP command windows | Not in unified coverage baseline | Behavioral proof only | Introduce marker-pinned CI smoke before post-merge where network stability allows |
| Frontend Playwright | `frontend` job | Provider-free browser UI specs under `apps/frontend/playwright` | Behavioral proof only; not in unified line coverage | Env-gated specs stay non-required until their env is provided in CI |
| Tier 3 Browser E2E | Staging/PR preview/prod smoke jobs | Playwright/HTTP deployment suites (`smoke`, `e2e`, `llm` split) | Behavioral/prod-risk proof only | Keep provider-dependent `llm` in post-merge; split provider-free subset for PR preview |

### PR vs Main CI Responsibilities

Pull requests run the same heavy CI path as `main` when runtime, tests, tooling,
CI, dependency, or coverage-policy files change. This keeps branch protection
strict before merge.

Pushes to `main` still run heavy CI for runtime changes even though the merged PR
already ran required checks. The retained post-merge run provides two signals
that PR checks cannot fully replace: validation of the exact merge commit and a
final local gate before post-merge staging/AI workflows consume the new commit.
Coverage regression detection is enforced locally against
`unified-coverage.json`; Coveralls remains main-only reporting and does not
decide CI pass/fail.

CI concurrency is deliberately different for PRs and `main`. Pull request runs
share a PR ref-scoped concurrency group and cancel superseded in-progress runs
to keep author feedback current. Pushes to `main` use a SHA-scoped concurrency
group, so rapid consecutive merges do not cancel or replace a pending main CI
run for an earlier merge commit. `workflow_dispatch` uses the run ID to keep
manual validations independent.

Lightweight changes do not repeat the heavy path on either PRs or `main`.
Lightweight means all changed files are limited to documentation, markdown,
issue templates, or `.github/workflows/docs.yml`. Other workflow changes are not
skipped because they may affect CI, deploy, or release behavior and must exercise
the full gate.

### Proof Placement Policy

The test system separates proof by where the failure can be acted on:

| Proof type | Runs where | Purpose |
|---|---|---|
| Behavioral tests | PR CI before merge | Prove deterministic product behavior, accounting invariants, API contracts, frontend flows, and tooling contracts before code enters `main`. |
| Schema migration contract | PR CI before merge | Prove Alembic can build the production schema from empty Postgres and that model definitions do not drift from generated migrations. |
| Migration risk contract | PR CI lint and production dry-run | Prove each Alembic revision has a right-sized risk classification. High and critical migrations must carry staging, production preflight, and rollback/expand-contract notes; this does not guarantee production data safety. |
| Environment gates | Post-merge deploy workflows | Prove the exact merged SHA can run in staging/production-like environments with real routing, Vault/Dokploy/GHCR/SigNoz wiring, deployed images, and provider-backed OCR/LLM credentials. |
| Reference traceability | PR and `main` CI | Prove every mandatory AC has a real non-placeholder test reference in a CI-required execution stage from `docs/ssot/test-execution-matrix.yaml`; this is not line coverage. |
| E2E EPIC traceability | PR and `main` CI | Prove every product E2E root `test_*` function has a function-level EPIC ID, every project EPIC has at least one product E2E owner test, the README EPIC map matches project EPIC files, and E2E-like assets are declared as product or non-product. |
| Critical proof matrix | PR and `main` CI | Prove README -> EPIC -> E2E macro closure and selected core proof paths instead of broad AC string references. |

Behavioral tests should move left into PR CI whenever they can be deterministic
without external singleton state or provider spend. Environment-dependent checks
belong in post-merge staging/production workflows because they validate the
deployed merge commit and shared infrastructure. A post-merge environment gate
must not be the first proof for deterministic business behavior.
Schema DDL correctness is deterministic and belongs in PR CI through
`schema-migrations`; preview and staging may catch environment-specific
deployment wiring, but they are not substitutes for migration proof.
Production data migration safety is not fully provable before production. The
migration risk contract classifies the risk and required evidence so staging is
used for the issues it can realistically catch, while production residual risk
is handled through preflight, backup, feature-flag, idempotency, and
post-deploy controls.

---

## No-Regression Coverage Gate

The CI workflow enforces a **no-regression policy** for test coverage.

### How It Works

1. **Baseline Storage**: `unified-coverage.json` at repo root.
   - Updated manually through PR when the coverage policy or measured baseline changes
   - Not auto-committed by CI because branch protection requires reviewed PRs

2. **Comparison Logic**:
   - Reads `unified-coverage.json` before calculating final coverage
   - Compares current vs baseline for **all components**: unified, backend, frontend, common, tools
   - Uses `round(x, 2)` for floating-point comparison
   - **Zero tolerance**: `current < baseline` → CI fails immediately
   - If baseline file missing: falls through to `COVERAGE_THRESHOLD` check (safety net)
3. **Source-tree/LCOV Logic**:
   - `common/coverage/policy.py` defines the single component policy used by coverage calculation and audit checks
   - `tools/check_ci_metrics_contract.py` first discovers source roots and fails CI when a new `apps/*/src`, `packages/*/src`, or root shared source root is not represented in `common/coverage/policy.py`
   - `tools/check_coverage_policy.py` compares eligible source files with LCOV `SF:` entries
   - `tools/build_unified_lcov.py` rewrites component-relative LCOV paths to repository-root-relative paths for Coveralls
   - New source modules are automatically required to appear in LCOV unless explicitly excluded by policy
   - New `apps/*/src`, `packages/*/src`, or root shared source roots fail CI until they are added to the coverage policy and report pipeline

4. **Metric Semantics**:
   - Line coverage is the only numeric source coverage metric enforced by the no-regression gate
   - AC traceability is a reference metric, not behavioral coverage
   - CI fails on mandatory AC coverage that is missing, placeholder-only, or stub-only; mandatory AC proof must also come from a CI-required execution stage in `docs/ssot/test-execution-matrix.yaml`
   - E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs, project EPICs without product E2E owner tests, README EPIC map drift, and unclassified E2E-like assets outside declared roots
   - The critical proof matrix protects only selected core proof paths from broad/reference-only AC strings
   - The source coverage matrix treats `required_source_classes` and per-source `proof_levels` as strict lists; scalar YAML values fail directly instead of being iterated character-by-character
   - Critical proof IDs are unique; duplicate IDs fail before mirror proof resolution can silently overwrite an earlier proof
   - Behavioral product coverage must be proven by Tier 1+ tests and explicit product E2E gates, not by an AC string appearing in a test file
   - Stub and placeholder assertions cannot count as proof; the CI gate runs before the traceability audit artifact is generated

5. **Environment Variables**:
   - `BASELINE_FILE`: Path to baseline JSON (default: `unified-coverage.json`)
   - `COVERAGE_THRESHOLD`: Safety net threshold (default: `0`; baseline comparison is primary gate)

### Manual Baseline Reset

```bash
# Option 1: Update baseline to current state
git pull origin main
# Make your changes, then:
git add unified-coverage.json && git commit -m "chore: manually reset coverage baseline" && git push

# Option 2: Remove baseline temporarily
git rm unified-coverage.json && git commit -m "chore: remove coverage baseline for testing" && git push
```

---

## Test Optimization

### Test Modes

| Mode | Command | Speed | Coverage | Use Case |
|------|---------|-------|----------|----------|
| Smart | `backend:test-smart` | ~40% | Changed files 99% | Daily dev (recommended) |
| Ultra-fast | `backend:test-no-cov` | ~30% | None | TDD red-green |
| Full | `backend:test` | 100% | All files 94% | CI/pre-commit |

### Implementation

**Tooling**:
- `tools/test_lifecycle.py --smart` — Runs backend tests with coverage on changed Python modules only
- `tools/test_lifecycle.py --fast` — Runs backend tests without coverage
- `tools/test_lifecycle.py` — DB lifecycle and namespace isolation for backend tests

**CI Optimization** (`.github/workflows/ci.yml`):
- Change classification is implemented in `tools/ci_change_classifier.py` and skips backend/frontend/unified coverage for lightweight docs and docs workflow changes.
- The classifier's primary contract is structured Env x Stage JSON outputs over the complete environment axis (`local`, `pr`, `pr-preview`, `staging`, `prd`): `env_stage_required`, `env_stage_reasons`, `env_stage_stages`, `env_stage_files`, and provider-gate JSON outputs. GitHub Actions consumers normalize gates from the structured matrix. Legacy scalar outputs such as `heavy_required`, `pr_preview_required`, `staging_required`, and `staging_ai_ocr_required` remain only as compatibility shims for external ad hoc consumers during migration.
- PR preview environments deploy only for runtime app, compose, root E2E, dependency, Dockerfile/config, or preview-action changes. Preview-action changes include `.github/workflows/pr-test.yml`, `.github/workflows/pr-preview-cleanup.yml`, `.github/actions/setup-e2e-tests/action.yml`, `tools/pr_preview_lifecycle.py`, and `tools/_lib/dev/pr_preview_lifecycle.py`. App test-only and app Markdown changes still run CI and AC gates without consuming a Dokploy preview slot.
- Automatic staging deploys are scoped to runtime app, deploy, root E2E, dependency, Dockerfile/config, staging workflow, toolchain, or infra-submodule changes. App test-only changes, documentation, project archive, AC traceability, and other tooling-only changes keep CI/AC gates but do not consume the staging singleton. The provider-backed AI/OCR gate is a narrower staging sub-gate: it runs only for provider, extraction, statement parsing, PDF fixture, AI/OCR workflow, or critical LLM proof path changes. Normal runtime deploys still run staging smoke and non-LLM E2E against the exact merged SHA.
- Markdown outside the documented lightweight trees is treated as heavy; this prevents runtime-adjacent README or tooling documentation changes from being hidden by a global `*.md` skip.
- Standalone lint and AC traceability start immediately with change classification. Deterministic test and image jobs start after change classification, then backend shards, frontend build/test, image build validation, tooling coverage, integration, and Tier-1 API E2E run in parallel. The `finish` job aggregates lint, AC traceability, deterministic tests, image validation, coverage, and skipped heavy-job semantics so earlier job starts improve wall-clock throughput without weakening merge authority.
- 6-way parallel test sharding via `pytest-split`
- Each shard: `pytest --splits 6 --group N`
- Tooling/common coverage runs in parallel as `tooling-coverage`; `unified-coverage` downloads `coverage-tooling` and merges backend, frontend, common, and tools LCOV inputs post-run.
- Coverage policy audited after backend, frontend, common, and tools LCOV reports exist
- Main-only Coveralls unified upload uses repository-root-relative backend + frontend + common + tools LCOV, matching the local unified calculation.
- Coveralls upload files strip branch records before upload so Coveralls reports the same line-only percentage as the deterministic unified coverage gate.
- PR CI does not call Coveralls and therefore cannot publish an external Coveralls status that disagrees with the local gate. Main push Coveralls upload is reporting-only and runs after local coverage gates pass.
- CI calls `tools/check_toolchain_contract.py` in lint before dependency installation and `tools/check_ci_metrics_contract.py` in lint before coverage jobs finish. Runtime versions and base images are owned by `toolchain.toml`, mirrored to local tool-manager files, and used by GitHub Actions, Dockerfiles, and `docker-compose.yml`.
- PR CI avoids Moon bootstrap in heavy runner jobs that execute direct `pytest` and `npm` commands. Backend shards, backend integration, Tier-1 API E2E, and the frontend build/test job use task-native commands directly so GitHub release CDN failures for optional Moon installation cannot mask deterministic code failures. Moon CLI availability and project graph coverage are static contracts over `.moon/toolchain.yml`, `moon.yml`, and app-level `moon.yml` files; runtime execution of Moon remains a local contributor responsibility and is not a PR merge gate unless a future workflow explicitly needs Moon semantics.
- PR CI dry-runs staging image builds before merge. The `container-images` job uses `docker/build-push-action` for both backend and frontend images with `push: false` on pull requests, then `finish` fails if that validation job fails.
- Main and release-branch push CI, plus on-demand `workflow_dispatch`, publish SHA-tagged images (P1a, #879). Registry login and image push are guarded by `(github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch'`; registry availability and authorization remain post-merge external-service risks, but Dockerfile, build-context, and build-argument errors are caught before merge.
- Frontend dependency installation uses `actions/setup-node@v4` with npm cache and deterministic `npm ci`. PR CI also runs `npm run audit:prod` after install so production frontend dependency advisories fail before merge; dev-only advisories remain outside this production gate.
- GitHub JavaScript action runtime is explicitly validated on Node 24 by setting `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` at the workflow level. This does not change the application toolchain `NODE_VERSION`; it only opts GitHub-hosted JavaScript actions into the runtime that GitHub will make the default.
- Production release tag builds and dry-runs verify that the target SHA already
  has a successful `main` CI `finish` result and a successful post-merge `staging`
  deployment, then run release lint and image promotion/validation. They do not
  rebuild images from source or rerun the container-backed `moon run :test`
  lifecycle in the release lane, maintaining the promote-not-rebuild consistency ladder
  where the exact same staging-validated image digest is promoted to production.
- The `finish` job appends a GitHub Step Summary from `tools/github_workflow_timing_summary.py` with queue delay, execution window, run wall time, longest completed job, and per-job durations.
- The `finish` job appends a coverage gate summary so reviewers can identify the authoritative local coverage gate.
- The `tooling-coverage` job uploads `coverage-tooling`; the `unified-coverage` job downloads it and uploads the `unified-coverage-context` artifact so reviewers can inspect raw line-count inputs instead of inferring failures from rounded percentages.
- CI observability artifacts are uploaded on success and failure for required test/deploy gates. Backend shards upload shard JUnit and LCOV, schema migrations upload Alembic logs and run context, frontend uploads Vitest JUnit plus Playwright report/test-results, AC traceability uploads gate status context with audit outputs, and environment workflows upload target SHA/URL/model/version context with E2E JUnit where available.
- Coveralls uploads are main-only reporting and do not block CI pass/fail when local deterministic gates pass.
- The repository ruleset must require the `finish` check, which aggregates local deterministic gates, rather than external reporting contexts.

**AC traceability audit artifact**:
- The current audit is generated in CI and uploaded as the `ac-test-traceability-audit` artifact.
- The AC traceability gate and audit builder share their default scan surface from
  `common/ssot/test_surface.py`; do not maintain parallel hard-coded test
  directory lists in individual tools.
- The same artifact includes `reconciliation-audit.json` and
  `reconciliation-audit.md` as hard-gated EPIC-004 accuracy evidence for the
  `>=95%` accuracy, `<0.5%` false-positive, `<2%` false-negative, and
  10,000-transaction runtime targets.
- Routine PRs must not commit generated snapshot reports solely because ACs or test references changed.
- The retired checked-in archive inventory is retained in [issue #548](https://github.com/wangzitian0/finance_report/issues/548), with full text recoverable from git history before commit `64aa58c`.

**Post-merge staging deploy health gate** (`.github/workflows/staging-deploy.yml`):
- Non-LLM smoke/E2E tests run in parallel with `-n 4`.
- The shared E2E setup action caches `.venv` and Playwright browsers so staging, manual AI/OCR, PR preview, and production smoke runs do not repeatedly download identical E2E dependencies.
- PR CI validates backend and frontend staging image builds without pushing so Dockerfile, context, and build-argument errors are blocked before merge. Main push CI builds and pushes SHA-tagged staging images in parallel with tests when heavy CI is required. These images are immutable commit artifacts and do not move the live `staging` tag.
- Automatic staging deploy starts only from a successful `push` `CI` `workflow_run` on `main`, and does not poll or wait for CI inside the deploy job. Failed, cancelled, timed-out, non-push, or non-main CI runs do not enter FIFO, promote images, push `staging` tags, or change the Dokploy staging environment.
- Before deploying, the staging workflow reuses `tools/ci_change_classifier.py` to compare the successful main CI SHA with its parent. Non-runtime documentation, project archive, AC traceability, and tooling-only changes stop after CI/AC proof and write a skip summary; runtime, deploy, E2E, staging workflow, toolchain, and infra-submodule changes still run the full staging deploy and non-LLM E2E. The workflow normalizes `env_stage_required.staging` for deploy relevance and `provider_gate_required.staging` for provider-backed replay relevance; only provider, extraction, statement parsing, PDF fixture, AI/OCR workflow, and critical LLM proof changes run the automatic provider-backed AI/OCR gate.
- Staging checks out the `workflow_run.head_sha` so the deployed SHA is the exact commit already proven by main push CI. Manual `workflow_dispatch` remains available as a recovery path and checks out the selected ref.
- Staging deploy context artifacts record triggering CI metadata: CI run id, run attempt, trigger event, head SHA, creation timestamp, conclusion, and run URL. They also record the structured build/deploy failure domain, failed step, and failure summary so early failures can be split between checkout/SHA resolution, post-merge train wait, change classification, toolchain setup, registry login, runner/Buildx bootstrap, GHCR image lookup/build/promotion, Dokploy rollout/health, E2E setup, and application smoke/E2E without manually scraping the raw job log first. The classifier fails closed: a failed classification step is never reported as `not-required`, and an unexpected failed step is reported as `unclassified-build-deploy-failure` rather than `none`.
- After successful main CI, post-merge staging first looks up the backend and frontend SHA-tagged staging images from GHCR. If a SHA image is missing, the workflow falls back to building only the missing image. Once both SHA images are present, staging retags those immutable images as `staging` before deploy. This keeps deploy detection strict while moving normal image build time out of the serialized post-merge lane.
- Deploy health covers image build/push, Dokploy rollout, `/api/health`, shell smoke checks, and core non-LLM E2E.
- Runtime incident classification for route, dependency, observability, secrets, stale-version, and flapping failures is owned by [runtime-incident-response.md](./runtime-incident-response.md). This CI/CD SSOT owns where the gates run and what they block, not the shared incident playbooks.
- Staging Dokploy rollout logs include a redacted rollout summary on the first, periodic, non-idle, error, and timeout probes. The summary may include compose identity, source path, command, compose status, deployment count, latest deployment status/timestamps, and deployment `logPath`; it must keep raw compose, raw deployment, and raw environment payloads out of GitHub Actions logs.
- Staging deploy proof is not satisfied by a Dokploy trigger alone. After `compose.deploy`, `tools/dokploy_deploy.sh` waits for Dokploy to expose a new deployment record and for that record to reach `done` before application readiness starts. A `running` deployment record only proves the worker started; it does not prove Docker containers and Traefik routes have materialized the target SHA. If `compose.deploy` does not expose a new deployment record within the short new-record window, staging retries once with `compose.redeploy`. It also retries once when `compose.deploy` leaves the compose in `error` before a new deployment record exists, because Dokploy can hold a stale compose error state while accepting a fresh environment update. If the redeploy still leaves the compose in `error`, staging fails as a Dokploy rollout failure with redacted rollout diagnostics. If the redeploy still does not expose a new record, staging fails before application readiness when no deployment record materializes instead of treating an accepted no-op request as deploy proof. `tools/health_check.sh` remains the final target-SHA proof after a completed rollout record; it must read `/api/health.git_sha` or `/api/health.version` and fail unless it matches the target image tag/SHA. If a new deployment record appears but does not reach `done`, staging fails as a platform rollout failure before application readiness.
- Automatic provider-backed AI/OCR validation runs as conditional downstream jobs in the same serialized post-merge workflow unit when the normalized staging provider gate is required. No two `Deploy Staging` workflow runs mutate staging concurrently: workflow-level singleton concurrency (`group: staging-deploy`, `cancel-in-progress: false`) admits one active staging train unit at a time, while the in-job FIFO guard still waits for older active runs before mutation.
- The lightweight AI provider connectivity smoke lives in the dedicated `Staging Provider Gate` job and runs only when `provider_gate_required.staging` is true. This single real chat round trip proves staging Vault/provider credentials, base URL, and primary model routing before the full PDF OCR replay spends provider quota. The full OCR/LLM replay remains gated to provider, extraction, statement parsing, PDF fixture, AI/OCR workflow, or critical LLM proof path changes and starts only after the provider connectivity smoke passes.
- The provider connectivity smoke is resilient to transient provider unavailability so a flaky upstream cannot red `main`. It retries the round trip with exponential backoff, then classifies the last observed outcome: a client/config `4xx` is a hard delivery gate (`config-failure`), while a `5xx`, timeout, or empty response is treated as transient and reported as a non-blocking `degraded` status. A degraded smoke still surfaces in the step summary, provider-gate artifact, staging alert issue, and `Post-merge Delivery` as `degraded-provider`, but it does not fail post-merge delivery. Provider configuration regressions therefore still block, transient provider blips do not.
- The in-job FIFO wait remains as a defensive ordering guard for already-active staging runs. Workflow-level singleton concurrency prevents duplicate concurrent deploy workflows, and `tools/wait_post_merge_train_turn.py` prevents a run from mutating staging while an older active `Deploy Staging` run is still completing. This keeps deploy, smoke, E2E, provider connectivity, and required AI/OCR proof as one ordered train unit for the workflow that owns the staging slot.
- Staging FIFO queueing bottleneck can be bypassed via parallel staging. The proposed path to parallel staging is to introduce multiple staging slots (e.g., `staging-1`, `staging-2`) or dynamic ephemeral staging environments using Docker Compose on the VPS, where each train unit or PR has its own ephemeral staging stack. This would allow multiple staging runs to execute in parallel, using a pool of database/MinIO instances, and dynamically routing to them via Traefik. This would bypass the 2-hour serial bottleneck.
- The staging deploy-health job has a 75-minute deploy-health job timeout, the FIFO train wait inside that job is parameterized via `STAGING_FIFO_TIMEOUT_SECONDS` (defaulting to 7200 seconds / 120 minutes, previously 21600 seconds / 360 minutes), and the E2E step has a 22-minute E2E step timeout. The deploy health probe waits up to 600 seconds for `/api/health` to report the target SHA so normal Dokploy/Traefik rollout lag does not fail before the deployed commit becomes visible. If `/api/health` is reachable but repeatedly reports the same stale SHA, staging uses `HEALTH_CHECK_MAX_SHA_MISMATCH_ATTEMPTS=18` to fail earlier with a Dokploy/image-pull/Traefik stale-route diagnosis instead of spending the full health window on a stable old deployment. The E2E command logs `[phase:start]` and `[phase:end]` records for smoke and core non-LLM E2E so timeout and latency failures identify the active phase.
- The automatic AI/OCR job has a 30-minute job timeout when it is required, while the provider-backed pytest step remains capped at 22 minutes.
- Staging deploys may set `DEPLOY_PRIMARY_MODEL_OVERRIDE`, `DEPLOY_OCR_MODEL_OVERRIDE`, and `DEPLOY_VISION_MODEL_OVERRIDE`; the current post-merge gate pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v`.
- Repeated `/api/health` 404 responses are treated as route failures, not generic backend failures: the health script emits structured `route_probe` lines and probes `/api/ping` and `/` so logs distinguish a missing or shadowed Traefik API route from an unhealthy backend container.
- Deploy dependency preflight lives in `tools/dokploy_deploy.sh` and the shared shell helpers it delegates to. Workflow-only no-op dependency checks and warning-only post-deploy performance probes are intentionally absent; deploy workflows keep only gates that can fail on release risk: image availability/build, Dokploy rollout, health, smoke, E2E, and provider-backed AI/OCR validation.
- Dokploy API failures must not print raw response bodies. Shared deploy helpers report only the endpoint, HTTP status, safe message fields, and `raw_body_printed=false`; compose responses can include environment data and refresh tokens. Rollout diagnostics may print only allowlisted compose/deployment fields such as compose status, deployment count, deployment id/status, safe message/error/reason fields, log path, and timestamps; they must truncate and redact token/password/secret/key-like values and print `raw_deployment_printed=false`.
- Staging and production deploys verify the effective Dokploy environment with an allowlist-only diff before triggering the rollout. The diff includes only `IMAGE_TAG`, `GIT_COMMIT_SHA`, `IAC_CONFIG_HASH`, `ENV_SUFFIX`, and `COMPOSE_PROFILES`; full environment strings and secret-like keys must not be logged.
- The post-merge workflow appends a GitHub Step Summary after deploy health and AI/OCR finish, making queue time, serial execution time, and slow jobs visible without manually scraping logs.
- The post-merge workflow also emits a dedicated `Post-merge Delivery` check for the merge commit. This aggregate check fails when staging classification, build/deploy, provider `4xx`/unknown hard failure, provider-backed AI/OCR, or staging alert propagation fails, and passes only when the whole deploy validation unit is complete, when classification proves staging is not required, or when a transient provider degradation is explicitly marked `degraded-provider`. A green `CI` workflow alone is not sufficient evidence that post-merge delivery passed.
- Automatic main post-merge staging failures and transient provider degradations create or update one persistent GitHub Issue alert titled `[staging-alert] Post-merge staging deploy failing`. Later failures or degradations append comments with the target SHA, run URL, staging URL, job results, provider connectivity result/status, structured build/deploy failure domain, failed step, failure summary, and current staging SHA; the next fully successful staging run comments and closes the issue. This is a CI/deploy visibility alert and does not replace SigNoz/Lark runtime alerting.

**Post-merge staging AI/OCR gate** (`.github/workflows/staging-ai-ocr-gate.yml`):
- Automatic `Staging AI/OCR Gate` execution lives in `.github/workflows/staging-deploy.yml` and starts only after deploy health succeeds in the same serialized post-merge workflow unit.
- `.github/workflows/staging-ai-ocr-gate.yml` remains as a manual recovery entry point via `workflow_dispatch` for rerunning provider-backed validation against the currently selected ref.
- Automatic AI/OCR gates inherit the deploy workflow's successful-main-CI `workflow_run` trigger before spending provider quota. If the matching CI run fails, is cancelled, or times out, automatic staging deploy and real OCR/LLM tests do not run.
- Tests marked `llm` are the only tests allowed to call the configured AI/OCR provider and run once, serially, in this provider-backed gate.
- PR CI does not spend real OCR/LLM quota, but tooling tests must still left-shift deterministic gate risks: every staging AI/OCR gate test must use isolated user fixtures, browser-cookie auth for in-browser API calls, and deterministic UI or route waits; contract tests reject shared mutable users, localStorage bearer tokens, and generic deployed-environment idle waits before merge.
- The automatic gate passes the deployed short SHA as `EXPECTED_SHA`, so version checks still validate the deployed commit before provider-backed parsing starts.
- The automatic gate checks out the full SHA emitted by `build-and-deploy` before setting up E2E tests. This keeps the test code, audit context, and deployed image under validation aligned to the same commit instead of the newest `main` ref.
- The GLM-backed PDF gate allows a longer parsing window than normal UI tests: JSON extraction requests use `AI_JSON_TIMEOUT_SECONDS=360`, and the browser gate waits up to `PARSING_TIMEOUT_MS=480000` so slow but successful `glm-4.6v` PDF parsing is not misclassified as a failed provider gate.
- The serialized GLM gate includes `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_statement_upload_e2e.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, and `tests/e2e/test_personal_financial_report_package.py`. The brokerage test uploads Moomoo and Futu PDF fixtures through `/api/statements/upload`, waits for parsed statements, imports positions through `/api/statements/{id}/brokerage/import`, and verifies `/api/portfolio/holdings` plus `/api/reports/balance-sheet`. The four-asset gate uses an isolated user to combine deterministic bank statement posting, brokerage PDF import, property/mortgage/ESOP manual valuation snapshots, exact as-of net worth, and dashboard/report totals. The personal financial report package gate verifies statements, schedules, notes, restricted-asset treatment, report exports, and source traceability from one fresh user. Failures identify whether OCR parsing, parsed-data state transition, brokerage import, manual valuation, reporting, report packaging, or dashboard aggregation failed. The path-level proof matrix is maintained in [EPIC-017](../project/EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix) with the compact entry-point version in the README; critical product proof anchors live in [critical-proof-matrix.yaml](critical-proof-matrix.yaml). Every `post_merge_environment` proof in that matrix that carries the `llm` marker must appear in both `.github/workflows/staging-deploy.yml` and `.github/workflows/staging-ai-ocr-gate.yml`.

**PR preview E2E** (`.github/workflows/pr-test.yml`):
- PR preview follows the matching successful PR `CI` `workflow_run`; it no
  longer polls partial CI from inside the preview workflow. Failed, cancelled,
  timed-out, non-PR, forked, or already-closed CI runs do not create a preview.
- PR preview does not inject `ZAI_API_KEY`; it validates app wiring without
  real GLM/OCR provider calls.
- PR preview does not push, preflight, pull, or delete PR preview images, and it
  does not build images in CI. The `build-preview-backend-image`,
  `build-preview-frontend-image`, `gate-cheap-ci`, and GHCR preflight/delete
  jobs are removed. The post-merge staging ladder remains the first place
  registry images are born, pushed, and validated.
- The runner stack uses `docker-compose.yml:docker-compose.ci-e2e.yml`,
  `COMPOSE_PROFILES=infra,app`, `APP_URL=http://localhost:8080`, and
  `GIT_COMMIT_SHA=<PR head SHA>`. The runner stack waits for `/api/health` before smoke/E2E, caps readiness at 300 seconds, emits compose logs on
  failure, and then always runs `docker compose down --volumes
  --remove-orphans`.
- After the in-runner E2E gate passes, a non-blocking `deploy-preview` job
  deploys a persistent per-PR Dokploy preview. It is GitHub-source: Dokploy
  clones the PR branch and runs `docker compose ... up -d --build` so the
  backend/frontend are **built from the PR source on the Dokploy host** — no
  GHCR image is pulled or pushed. The job is `continue-on-error` and is not a
  required check, so a preview failure never blocks the PR; the in-runner E2E is
  the merge authority. The persistent URL is `https://report-pr-<N>.<domain>`.
- `tools/pr_preview_lifecycle.py` is the single owner for preview deploy,
  cleanup, and scheduled reconciliation. The workflow does not hand-roll
  separate Dokploy shell blocks because deploy, cleanup, and reconciliation must
  share the same naming, metadata, logging, and redaction contract.
- PR preview Dokploy API responses are parsed for required fields only.
  Workflows must not print raw Dokploy response JSON because compose responses
  can include environment data and refresh tokens.
- The in-runner E2E result comment and context artifact record
  `preview_runtime=github-runner-compose`,
  `persistent_preview_url=https://report-pr-<N>.<domain>`,
  `registry_image_push=false`, and
  `dokploy_deploy=after-e2e-non-blocking-build-from-source`. The persistent
  preview URL is posted as a separate non-blocking comment.
- Persistent preview cleanup runs on PR close/merge, failed CI, cancelled CI,
  and timed-out CI via `tools/pr_preview_lifecycle.py --action cleanup` (native
  Dokploy `compose.delete`) by PR number/compose name rather than broad volume
  pruning. The deploy path is get-or-create + redeploy, so it updates the
  preview in place across commits without a pre-deploy delete.
- PR preview E2E explicitly excludes tests marked `llm`. The post-merge `Staging AI/OCR Gate` workflow is the single automated CI entry point that may spend provider quota.
- PR preview non-LLM E2E is a strict preview-relevant subset: `STRICT_E2E_GATES=true`, marker `(smoke or e2e) and not llm`, `-n 4` parallelism, and explicit paths limited to `tests/e2e/test_core_journeys.py` plus `tests/e2e/test_e2e_flows.py::test_full_navigation`. Broader business regression paths, provider-sensitive paths, and state-sensitive registration or statement workflows remain staging/post-merge responsibilities.
- The shared `.github/actions/setup-e2e-tests` action owns E2E Python import setup. It must export the repository root through `PYTHONPATH` via `$GITHUB_ENV` before preview, staging, AI/OCR, or production E2E pytest commands run, because `tests/e2e/conftest.py` imports shared helpers through the `tests.e2e.*` package path while pytest may choose `tests/e2e` as its root directory.
- PR preview cleanup has two lifecycle paths: PR-driven cleanup removes legacy
  Dokploy stacks for closed/merged/interrupted PRs; the scheduled `PR Preview
  Cleanup` fallback runs Dokploy compose reconciliation for closed or missing
  historical previews and prunes legacy closed-PR backend/frontend GHCR tags
  matching `pr-<number>-<sha>` after the 14-day retention window while
  preserving tags for open PRs. GitHub workflows must not SSH to the VPS for PR
  cleanup. Scheduled reconciliation must not own generic host hygiene, global
  Docker volume pruning, `docker system prune --volumes`, build-cache pruning,
  image pruning, or journal vacuuming.
- `tools/cleanup_pr_preview_resources.py` is a deprecated compatibility entry point and must not perform SSH cleanup or host-wide Docker/journal pruning. Closed-PR leftovers use `tools/pr_preview_lifecycle.py --action reconcile`; host hygiene uses the Dokploy `dokploy-server` schedule managed by `tools/vps_host_hygiene.py --ensure-dokploy-schedule`.
- PR preview containers created from `docker-compose.yml` use the `json-file` logging driver with bounded `max-size` and `max-file` options so Docker container logs cannot grow without limit between scheduled cleanup runs.
- Generic VPS host hygiene runs as a Dokploy `dokploy-server` Schedule Job. The `dokploy-server` type is mandatory: the legacy `server` type with a null `serverId` is accepted by `schedule.create` but never executes the command — a silent no-op that previously let orphaned resources accumulate. It prunes old stopped non-preview containers, old build cache, old unused images, all unused Docker networks, oversized Docker json logs, and systemd journal retention. Unused Docker networks are not age-gated because Docker's predefined address pools can be exhausted by orphan networks before disk age thresholds are reached; Docker will not remove networks attached to running containers. Host hygiene is **generic-only**: it does not fetch open PRs or remove PR preview containers/volumes. PR preview environments are reaped natively by Dokploy `compose.delete` (reliable since Dokploy v0.29.x); the `PR_PREVIEW_CONTAINER_PATTERN` is retained solely to *exclude* Dokploy-owned preview containers from generic stopped-container pruning. This keeps host disk policy independent from GitHub Actions SSH access while using Dokploy as the operational scheduler.
- GLM/OCR CI traffic uses `AI_BASE_URL=https://api.z.ai/api/coding/paas/v4`; the URL remains an env override so the base provider can be replaced without code changes.

**Production release dry-run** (`.github/workflows/production-release.yml`):
- Manual `workflow_dispatch` with `dry_run=true` verifies the target SHA's successful `main` CI result, a successful staging deployment, runs release lint, and dry-runs image promotion by verifying that staging-validated SHA-tagged images exist on GHCR and retrieving their digests without pushing any tags.
- The dry-run reports the validated ref/tag, the staging run checked, the target image digests, and states that production mutation was skipped. No rebuild occurs.
- Tag pushes remain the only automatic path that promotes versioned release images. Manual dispatch with `dry_run=false` remains the production deploy path for an existing version.
- Production backend release images carry the original commit's `GIT_COMMIT_SHA`, and Dokploy deploys inject the release version tag as the runtime `IMAGE_TAG` / `GIT_COMMIT_SHA` so `/api/health` can prove the deployed version even after a same-tag redeploy.
- Production deploys run `tools/production_infra_smoke.py` after health check. That gate verifies the deployed version, `/api/health` dependency checks for database and S3, read-only `/api/ping`, frontend reachability, and the shared SigNoz health/version endpoints before production smoke and read-only E2E run.
- Production deploy context records the pre-deploy health status and `production_before_version`, image verification outcome, deploy-health outcome, infrastructure smoke outcome, application smoke outcome, read-only E2E outcome, and a small failure-domain classification. Production still proves release integrity and health only; first-time business correctness remains owned by PR and staging gates.

The remaining higher-risk CI and post-merge optimization candidates are tracked
in the delivery-engine recommendation note instead of being mixed into routine
SSOT edits: [DELIVERY_ENGINE_RECOMMENDATIONS.md](../project/DELIVERY_ENGINE_RECOMMENDATIONS.md).

> **Local vs GitHub CI Parallelism**
>
> | Environment | Parallelism | Test Scope | Resource Usage |
> |-------------|-------------|------------|----------------|
> | **GitHub CI** | `-n auto` + `--splits 6` | ~17% tests per shard | Medium (ephemeral runners) |
> | **Local CI** | `-n 4` (fixed) | 100% tests | Controlled (shared machine) |
>
> This is intentional design, not inconsistency.

---

## Coverage Requirements

- Backend default local/pre-push coverage: enforced by `apps/backend/pyproject.toml`.
- Frontend local coverage: enforced by `apps/frontend/vitest.config.ts`.
- PR/main unified coverage: **no regression from `unified-coverage.json`** across backend, frontend, common, and tools.
- CI backend shards set `--cov-fail-under=0`; per-shard percentages are artifacts, while the merged unified job is the stable source of truth.
- Branch coverage may be collected locally and by backend pytest, but the unified gate and Coveralls uploads are line-only.
- See [coverage.md](./coverage.md) and [tdd.md](./tdd.md) for details

---

## Current Performance Metrics

**CI Pipeline (2025-02-02 baseline):**
- Total duration: **6m 24s** (Backend: 5m 52s, Frontend: 1m 30s)
- Test execution: 893 tests in 4m 47s (**320ms avg**)
- Caching: UV ✅ (2.9s), Next.js ✅, venv ✅

**CI Pipeline (2026-05-19 observed baseline):**
- Full heavy CI on `main`: **~7m 39s** before 6-way backend sharding.
- Longest backend shard: **~6m 23s** before 6-way backend sharding.
- Frontend build and coverage test: **~2m 32s** before npm cache standardization.
- Unified coverage: **~28s**.
- Lightweight docs/docs-workflow changes skip backend, frontend, and unified coverage; lint, AC traceability, and finish still run.

**CI Pipeline (2026-05-20 after 6-way backend sharding):**
- Full heavy CI execution window on `main`: **~5m 48s** after jobs start; run wall time may be higher when GitHub queues the run.
- Longest backend shard: **~4m 48s**.
- Unified coverage: **~42s**, including tooling coverage and reporting-only Coveralls uploads before the tooling/common coverage split.
- The timing summary reports queue delay separately from execution time so future regressions can distinguish runner capacity from workflow critical-path changes.

**Post-merge staging (2026-05-20 observed baseline):**
- Build and deploy job execution: **~5m 19s**.
- Automatic AI/OCR gate execution: **~4m 38s**.
- AI/OCR `Setup E2E Tests`: **~2m 54s** before E2E virtualenv and Playwright browser caching.

**Post-merge staging image promotion (2026-05-21 target):**
- Main push CI owns SHA-tagged staging image creation for heavy runtime changes.
- The serialized staging lane promotes existing SHA images to the moving `staging` tag after successful main CI workflow_run validation, avoiding redundant Docker builds in the normal path.
- Missing SHA images trigger a per-service fallback build, preserving deployability for manual reruns and unusual cache/package states.

**Backend Test Parallelization:**

```bash
# In pyproject.toml
[tool.pytest.ini_options]
addopts = "-n 2"  # 2 workers for parallel execution
```

Options:
1. **Increase worker count**: `pytest -n auto` or `pytest -n 4` (limited by CPU cores)
2. **Split CI jobs**: Separate unit vs integration in GitHub Actions (1-2 min savings)

---

## Smoke Tests (`tools/smoke_test.sh`)

```bash
# Local (after starting servers)
bash tools/smoke_test.sh

# Against staging/prod
BASE_URL=https://report.zitian.party bash tools/smoke_test.sh
```

| Endpoint | Check |
|----------|-------|
| `/` | Homepage loads |
| `/api/health` | Returns "healthy" |
| `/api/docs` | Swagger UI loads |
| `/ping-pong` | Demo page loads |
| `/reconciliation` | Workbench loads |
| `/api/ping` | Ping API responds |

## Deploy E2E Gates

Staging and production deploy workflows separate basic availability smoke from
deploy-blocking usability gates:

| Environment | Gate | Command | Skip Policy |
|-------------|------|---------|-------------|
| Staging | Shell smoke | `bash tools/smoke_test.sh "$APP_URL" staging` | No skips; any failed check fails deploy |
| Staging | Non-LLM E2E | `STRICT_E2E_GATES=true pytest tests/e2e -v -m "(smoke or e2e) and not llm" -n 4` | Tests marked `critical` must fail instead of skip |
| Staging | AI/OCR E2E | `STRICT_E2E_GATES=true pytest tests/e2e/test_statement_full_journey.py tests/e2e/test_brokerage_upload_to_portfolio_value.py tests/e2e/test_four_asset_net_worth_golden_path.py tests/e2e/test_personal_financial_report_package.py tests/e2e/test_statement_upload_e2e.py -v -m "llm"` | Serial provider-backed GLM gate; `rejected` fails deploy |
| Production | Shell smoke | `bash tools/smoke_test.sh https://report.zitian.party production` | Read-only checks only |
| Production | Prod-safe E2E | `pytest tests/e2e/test_production_readonly_smoke.py -v -m "prod_safe"` | Authenticated dashboard check may skip only when read-only smoke credentials are absent |

Critical staging E2E tests are the proof that a deployment is usable, not just
reachable. `tests/e2e/test_statement_full_journey.py::test_dbs_statement_full_journey`
is the AI/OCR hard gate: DBS PDF upload must reach `parsed`, show transactions,
approve, and load the balance sheet. A `rejected` parsing status is a deploy
failure because it usually indicates AI provider, OCR, secret, or model config
breakage. Rejection failures include the selected model and statement validation
context (`validation_error`, `confidence_score`, and
`balance_validated`) so the post-merge gate is actionable from the CI log.

`tests/e2e/test_vision_upload_to_dashboard_hard_gate.py::test_statement_upload_to_dashboard_vision_hard_gate`
is the deterministic upload-to-dashboard vision hard gate. It runs in the
staging non-LLM deploy gate with a fresh isolated user, uploads a deterministic
CSV fixture, verifies Stage 1 auto-posted journal entries, reruns
reconciliation to a cleared Stage 2 state, asserts Processing visibility, and
checks exact dashboard, balance-sheet, income-statement, and cash-flow totals.

`tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value`
is the upload-to-report portfolio hard gate for Issue #404. It proves that at
least two brokerage PDFs can be parsed by the real configured OCR path, imported
as portfolio positions, and reflected in the latest balance-sheet market
valuation adjustment lines. The gate intentionally does not compare imported
holdings to whole `total_assets`: unrelated staging ledger lines, including
negative cash or bank balances from other E2E journeys, can lower total assets
without invalidating portfolio valuation coverage. Failure output includes the
holdings total market value, valuation adjustment total, non-portfolio asset
total, total assets, net worth adjustment, and relevant asset lines.

`tests/e2e/test_four_asset_net_worth_golden_path.py::test_four_asset_as_of_net_worth_golden_path`
is the north-star net-worth hard gate for Issue #444. It uses an isolated user
to upload bank statement data, explicitly post and reconcile the statement,
import a brokerage PDF, create property, mortgage, and ESOP valuation snapshots,
then prove exact as-of assets, liabilities, net worth, and dashboard/report
totals.

PR preview E2E intentionally runs a strict runtime/API/UI subset, currently
`tests/e2e/test_core_journeys.py` plus
`tests/e2e/test_e2e_flows.py::test_full_navigation`, excludes the `llm` marker,
and does not inject the provider API key. This keeps provider spend and broad
business-regression concurrency concentrated in the post-merge staging job,
where `STRICT_E2E_GATES=true` makes provider/config failures block deploy. PR
preview remains useful for app wiring and non-provider route proof without
turning provider instability or state-sensitive staging regressions into PR
preview noise.

---

## Related

- [development.md](./development.md) — Moon commands and local setup
- [environments.md](./environments.md) — Six environment overview
- [coverage.md](./coverage.md) — Unified coverage system
- [tdd.md](./tdd.md) — TDD workflow and coverage goals
