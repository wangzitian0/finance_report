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
| **backend** (Shards 1-6) | Backend fast-path tests only: `-m "not slow and not e2e and not integration"` | `needs: [changes]` |
| **backend-integration** | Backend integration stage (`-m "integration"`), deterministic service-backed behavior checks | `needs: [changes]` |
| **backend-e2e-tier1** | Backend Tier-1 API E2E stage (`apps/backend/tests/e2e/test_core_journeys.py` with `-m e2e`), executed with explicit marker override | `needs: [changes]` |
| **frontend** | Frontend build + Vitest + Playwright tests when heavy CI is required | `needs: [changes]` |
| **container-images** | Build backend and frontend staging images without pushing on PRs; push SHA-tagged images only on `main` | `needs: [changes]` |
| **tooling-coverage** | Run root tooling tests with common/tools coverage and upload LCOV inputs | `needs: [changes]` |
| **unified-coverage** | Merge backend, frontend, common, and tools LCOV inputs, audit source-tree/LCOV policy, calculate unified coverage, compare to baseline, update Coveralls when heavy CI is required | `needs: [changes, backend, frontend, tooling-coverage]` |
| **ac-traceability** | Verify AC-to-test traceability for all PR/main changes, including docs-only changes | None |
| **finish** | Aggregate all required and skipped job results | `needs: [changes, backend, backend-integration, backend-e2e-tier1, frontend, container-images, lint, tooling-coverage, unified-coverage, ac-traceability]` |

### Key CI Properties

1. **Standalone Lint Job**: Runs independently; lint failures surface in ~1 min (not after 10 min backend shard).
2. **Change Classification**: Lightweight documentation, issue-template, markdown, and `.github/workflows/docs.yml` changes skip backend, frontend, and unified coverage. Runtime, test, tooling, CI, dependency, and coverage-policy changes run the full heavy path.
3. **Stable Required Checks**: Heavy jobs are skipped through job-level conditions rather than removing the workflow, so required check names remain visible and mergeable.
4. **AC Traceability Always Runs**: AC traceability is separate from unified coverage so docs-only AC/EPIC changes still get traceability validation. The job first runs `tools/generate_ac_registry.py --check` to ensure generated registry indexes can be materialized from EPIC docs plus explicit overrides, then runs `tools/check_ac_traceability.py` as the fail-closed gate, then runs `tools/check_e2e_epic_traceability.py` to ensure product E2E root test functions carry function-level EPIC IDs, every project EPIC has product E2E ownership, the README EPIC map matches project EPIC files, and unclassified E2E-like assets outside declared roots fail CI, then runs `tools/check_critical_proof_matrix.py` to validate the small core proof matrix, then generates `AC-TEST-TRACEABILITY-AUDIT.md` into `$RUNNER_TEMP`; the audit is uploaded as a CI artifact together with the critical proof matrix report. The job also runs `tools/reconciliation_audit.py` through the backend uv environment as a hard gate and uploads reconciliation audit JSON/Markdown with the same artifact. The audit distinguishes CI-executed real test references from `_ac_stubs`, trivial placeholder assertions, pure `pass`, pure skipped tests, and real references that live only in non-required execution stages. `docs/ssot/test-execution-matrix.yaml` owns the path-to-stage mapping. CI fails on mandatory AC coverage that is missing, placeholder-only, stub-only, or real-only outside CI-required stages; full-strikethrough deprecated ACs are excluded from the mandatory gate. The macro gate fails README/matrix/owner-EPIC drift, E2E/EPIC ownership drift, and broad/reference-only critical proof anchors. The generated audit is uploaded as a CI artifact; checked-in archive copies were retired to reduce merge conflicts.
5. **Generated API reference is code-owned**: Static API reference docs are generated from FastAPI OpenAPI by `tools/generate_api_reference.py`. PR CI runs `python ../../tools/generate_api_reference.py --check` inside the backend uv environment after dependencies are installed, so endpoint paths, parameters, request schemas, response schemas, and enum values cannot drift into hand-written Markdown.
6. **Backend stages are explicit and split**: Backend fast-path remains shard stage (`backend`) with `-m "not slow and not e2e and not integration"`. Standalone gates start immediately: `lint` and `ac-traceability` have no `needs` dependency and run in parallel with change classification. Deterministic test and image jobs start after change classification and do not wait for lint, AC traceability, or behavior-only backend gates. Behavior-only backend gates run in parallel as explicit `backend-integration` and `backend-e2e-tier1` stages, and finish remains the authoritative aggregate gate for lint, AC traceability, tests, image validation, coverage, and skipped heavy-job semantics.
7. **Coverage Debug Context Is Always Uploaded**: The `tooling-coverage` job uploads `coverage-tooling` with `coverage/common.lcov` and `coverage/tools.lcov`; the `unified-coverage` job downloads that artifact and uploads `unified-coverage-context` on success and failure. The unified artifact contains `coverage/backend.lcov`, `coverage/frontend.lcov`, `coverage/common.lcov`, `coverage/tools.lcov`, the current `unified-coverage.json`, and `coverage/coverage-context.txt` with raw line-count inputs, commit/event/run metadata, toolchain versions, and input hashes. Coverage regressions must be diagnosed from these artifacts before treating a percentage delta as nondeterminism.
8. **CI Observability Artifacts Are Failure-Path Owned**: Backend shard, backend integration, backend Tier-1 E2E, frontend Vitest, frontend Playwright, tooling/common coverage, AC traceability, PR preview, staging, manual AI/OCR, production release, and scheduled cleanup gates publish CI observability artifacts with `if: always()`. These artifacts include JUnit XML where pytest or Vitest/Playwright can produce it, raw coverage/report inputs where relevant, and a small context file with repository/event/ref/SHA/run metadata plus target environment/version fields. Step summaries remain human-readable status pages; artifacts are the replayable evidence for both success and failure.
9. **Coveralls Is Main-Only Reporting**: Pull requests do not call Coveralls and therefore do not publish external Coveralls status contexts. CI pass/fail is decided by local gates (`tools/check_ci_metrics_contract.py`, `tools/check_coverage_policy.py`, `tools/calculate_unified_coverage.py`) aggregated by `finish`. Main pushes upload only the unified line-only LCOV report to Coveralls for badge and trend reporting after the local coverage gate passes. Backend/frontend per-flag Coveralls uploads are intentionally absent so a single commit has one reporting denominator.
10. **Single CI Metrics Contract**: `tools/check_ci_metrics_contract.py` is the single CI metrics contract. It runs in `lint` and validates that source-root discovery, `common/coverage/policy.py`, workflow gates, and AC traceability semantics stay aligned before coverage jobs finish.
11. **Toolchain Contract**: `tools/check_toolchain_contract.py` runs in lint and fails when Python, Node.js, uv, Docker base images, Compose service images, or frontend engine constraints drift from `toolchain.toml`.
12. **PR Image Build Validation**: PR CI dry-runs staging image builds before merge with the same Dockerfiles, contexts, and build arguments used by `main`. Main push CI is the only path that pushes SHA-tagged images to GHCR.
13. **Coverage Policy Audit**: `tools/check_coverage_policy.py` fails CI if backend, frontend, common, or tools source files drift from their LCOV report.
14. **No-regression gate**: Zero-tolerance; if ANY component is below baseline, CI fails immediately.
15. **Deny-list coverage scope**: Coverage scope is deny-list based within each governed source root. CI recursively expects every eligible source file in backend, frontend, common, and tools LCOV unless `common/coverage/policy.py` explicitly excludes it. New source roots fail the metrics contract until added to the policy and report pipeline.

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
| `pr-preview` | no | no | no | no | runtime/UI/API preview-relevant subset | push PR images | required health/version | no | no |
| `staging` | no | no | no | no | merged-SHA non-LLM and provider-backed regression | reuse or build missing SHA images | required | required where source class needs real provider proof | no |
| `prd` | no | no | no | no | prod-safe smoke only | release image proof | required | no first-time proof | required |

Production release proof is intentionally narrow: production validates release
integrity and availability, not first-time deterministic business behavior.

### Path Risk to Local Gate Matrix

Default local verification starts with affected fast tests such as
`moon run :test -- --smart`, focused Vitest/spec runs, or the smallest relevant
tooling contract. Risk-triggered local escalation applies when the changed path
can affect behavior outside the touched file.

| Changed path or concern | Default local gate | Escalation trigger |
|---|---|---|
| Ordinary backend source | `moon run :test -- --smart` or focused pytest file | Escalate when the change crosses service boundaries or touches shared helpers |
| accounting, posting, reconciliation, money, balance | Focused domain pytest suite plus changed-file tests | Always include invariant tests beyond the touched file |
| schema, migrations | Migration validation plus DB-backed integration tests | Required for any Alembic, SQLAlchemy model, enum, or persistence contract change |
| API contract, OpenAPI | Backend API tests plus affected frontend API consumer tests | Required for route, schema, generated API reference, or response-shape changes |
| Frontend component or route | Focused Vitest/spec, then affected Playwright when browser behavior changes | Escalate for navigation, responsive layout, workflow, or API-bound behavior |
| shared common/tooling | Focused tooling tests plus affected downstream contracts | Escalate when a common package feeds CI, coverage, SSOT, or command wrappers |
| Docker, workflow, environment, deploy | Static/tooling contract checks locally; PR CI and deployed gates own runtime proof | Required image/deploy proof stays in PR CI, PR Preview, staging, or production |
| docs-only | SSOT/doc/traceability checks only | Escalate only when docs change workflow, registry, AC, or proof semantics |

### Stage Matrix and Left-Move Guidance

| Stage | Current execution | Scope in CI | Coverage effect | Left-move action |
|---|---|---|---|---|
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
| Environment gates | Post-merge deploy workflows | Prove the exact merged SHA can run in staging/production-like environments with real routing, Vault/Dokploy/GHCR/SigNoz wiring, deployed images, and provider-backed OCR/LLM credentials. |
| Reference traceability | PR and `main` CI | Prove every mandatory AC has a real non-placeholder test reference in a CI-required execution stage from `docs/ssot/test-execution-matrix.yaml`; this is not line coverage. |
| E2E EPIC traceability | PR and `main` CI | Prove every product E2E root `test_*` function has a function-level EPIC ID, every project EPIC has at least one product E2E owner test, the README EPIC map matches project EPIC files, and E2E-like assets are declared as product or non-product. |
| Critical proof matrix | PR and `main` CI | Prove README -> EPIC -> E2E macro closure and selected core proof paths instead of broad AC string references. |

Behavioral tests should move left into PR CI whenever they can be deterministic
without external singleton state or provider spend. Environment-dependent checks
belong in post-merge staging/production workflows because they validate the
deployed merge commit and shared infrastructure. A post-merge environment gate
must not be the first proof for deterministic business behavior.

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
- PR preview environments deploy only for runtime app, compose, root E2E, dependency, Dockerfile/config, or preview-action changes. Preview-action changes include `.github/workflows/pr-test.yml`, `.github/workflows/pr-preview-cleanup.yml`, `.github/actions/setup-e2e-tests/action.yml`, `tools/pr_preview_lifecycle.py`, and `tools/_lib/dev/pr_preview_lifecycle.py`. App test-only and app Markdown changes still run CI and AC gates without consuming a Dokploy preview slot.
- Automatic staging deploys are scoped to runtime app, deploy, root E2E, dependency, Dockerfile/config, staging workflow, toolchain, or infra-submodule changes. App test-only changes, documentation, project archive, AC traceability, and other tooling-only changes keep CI/AC gates but do not consume the staging singleton.
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
- PR CI dry-runs staging image builds before merge. The `container-images` job uses `docker/build-push-action` for both backend and frontend images with `push: false` on pull requests, then `finish` fails if that validation job fails.
- Main push CI is the only path that pushes SHA-tagged images. Registry login and image push are guarded by `github.event_name == 'push' && github.ref == 'refs/heads/main'`; registry availability and authorization remain post-merge external-service risks, but Dockerfile, build-context, and build-argument errors are caught before merge.
- Frontend dependency installation uses `actions/setup-node@v4` with npm cache and deterministic `npm ci`. PR CI also runs `npm run audit:prod` after install so production frontend dependency advisories fail before merge; dev-only advisories remain outside this production gate.
- GitHub JavaScript action runtime is explicitly validated on Node 24 by setting `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` at the workflow level. This does not change the application toolchain `NODE_VERSION`; it only opts GitHub-hosted JavaScript actions into the runtime that GitHub will make the default.
- Production release tag builds and dry-runs verify that the target SHA already
  has a successful `main` CI `finish` result, then run release lint and image
  build validation. They do not rerun the container-backed `moon run :test`
  lifecycle in the release lane.
- The `finish` job appends a GitHub Step Summary from `tools/github_workflow_timing_summary.py` with queue delay, execution window, run wall time, longest completed job, and per-job durations.
- The `finish` job appends a coverage gate summary so reviewers can identify the authoritative local coverage gate.
- The `tooling-coverage` job uploads `coverage-tooling`; the `unified-coverage` job downloads it and uploads the `unified-coverage-context` artifact so reviewers can inspect raw line-count inputs instead of inferring failures from rounded percentages.
- CI observability artifacts are uploaded on success and failure for required test/deploy gates. Backend shards upload shard JUnit and LCOV, frontend uploads Vitest JUnit plus Playwright report/test-results, AC traceability uploads gate status context with audit outputs, and environment workflows upload target SHA/URL/model/version context with E2E JUnit where available.
- Coveralls uploads are main-only reporting and do not block CI pass/fail when local deterministic gates pass.
- The repository ruleset must require the `finish` check, which aggregates local deterministic gates, rather than external reporting contexts.

**AC traceability audit artifact**:
- The current audit is generated in CI and uploaded as the `ac-test-traceability-audit` artifact.
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
- Before deploying, the staging workflow reuses `tools/ci_change_classifier.py` to compare the successful main CI SHA with its parent. Non-runtime documentation, project archive, AC traceability, and tooling-only changes stop after CI/AC proof and write a skip summary; runtime, deploy, E2E, staging workflow, toolchain, and infra-submodule changes still run the full staging deploy, non-LLM E2E, and AI/OCR gate.
- Staging checks out the `workflow_run.head_sha` so the deployed SHA is the exact commit already proven by main push CI. Manual `workflow_dispatch` remains available as a recovery path and checks out the selected ref.
- Staging deploy context artifacts record triggering CI metadata: CI run id, run attempt, trigger event, head SHA, creation timestamp, conclusion, and run URL.
- After successful main CI, post-merge staging first looks up the backend and frontend SHA-tagged staging images from GHCR. If a SHA image is missing, the workflow falls back to building only the missing image. Once both SHA images are present, staging retags those immutable images as `staging` before deploy. This keeps deploy detection strict while moving normal image build time out of the serialized post-merge lane.
- Deploy health covers image build/push, Dokploy rollout, `/api/health`, shell smoke checks, and core non-LLM E2E.
- Staging deploy proof is not satisfied by a Dokploy trigger alone. After `compose.deploy`, `tools/dokploy_deploy.sh` first waits up to 600 seconds for Dokploy to expose a new deployment record and for that record to reach `done` before application readiness starts. A `running` deployment record only proves the worker started; it does not prove Docker containers and Traefik routes have materialized the target SHA. If no new deployment record appears within that worker-queue window, or the new record does not finish, the deploy fails as a platform rollout failure instead of spending the health window on a stale SHA. After the Dokploy rollout gate passes, `tools/health_check.sh` must read `/api/health.git_sha` or `/api/health.version` and fail unless it matches the target image tag/SHA.
- Automatic provider-backed AI/OCR validation runs as a downstream job in the same serialized post-merge workflow unit. This keeps staging stable for the SHA under validation: a newer deploy cannot overwrite staging while an older automatic AI/OCR gate is running.
- Staging deploys use an explicit FIFO post-merge train gate instead of workflow-level concurrency. Every successful main CI `workflow_run` is preserved as its own `Deploy Staging` run; before any run mutates staging, `tools/wait_post_merge_train_turn.py` waits for all older active `Deploy Staging` workflow runs to fully complete. This avoids GitHub Actions concurrency's one-pending-run replacement behavior and keeps each merge commit's deploy, smoke, E2E, and AI/OCR proof as one ordered train unit.
- The staging deploy-health job has a 75-minute deploy-health job timeout, the FIFO train wait has a 360-minute timeout, and the E2E step has a 22-minute E2E step timeout. The deploy health probe waits up to 600 seconds for `/api/health` to report the target SHA so normal Dokploy/Traefik rollout lag does not fail before the deployed commit becomes visible. The E2E command logs `[phase:start]` and `[phase:end]` records for smoke and core non-LLM E2E so timeout and latency failures identify the active phase.
- The automatic AI/OCR job has a 30-minute job timeout, while the provider-backed pytest step remains capped at 22 minutes.
- Staging deploys may set `DEPLOY_PRIMARY_MODEL_OVERRIDE`, `DEPLOY_OCR_MODEL_OVERRIDE`, and `DEPLOY_VISION_MODEL_OVERRIDE`; the current post-merge gate pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v`.
- Repeated `/api/health` 404 responses are treated as route failures, not generic backend failures: the health script probes `/api/ping` and `/` so logs distinguish a missing or shadowed Traefik API route from an unhealthy backend container.
- Deploy dependency preflight lives in `tools/dokploy_deploy.sh` and the shared shell helpers it delegates to. Workflow-only no-op dependency checks and warning-only post-deploy performance probes are intentionally absent; deploy workflows keep only gates that can fail on release risk: image availability/build, Dokploy rollout, health, smoke, E2E, and provider-backed AI/OCR validation.
- Dokploy API failures must not print raw response bodies. Shared deploy helpers report only the endpoint, HTTP status, safe message fields, and `raw_body_printed=false`; compose responses can include environment data and refresh tokens.
- Staging and production deploys verify the effective Dokploy environment with an allowlist-only diff before triggering the rollout. The diff includes only `IMAGE_TAG`, `GIT_COMMIT_SHA`, `IAC_CONFIG_HASH`, `ENV_SUFFIX`, and `COMPOSE_PROFILES`; full environment strings and secret-like keys must not be logged.
- The post-merge workflow appends a GitHub Step Summary after deploy health and AI/OCR finish, making queue time, serial execution time, and slow jobs visible without manually scraping logs.
- The post-merge workflow also emits a dedicated `Post-merge Delivery` check for the merge commit. This aggregate check fails when staging classification, build/deploy, provider-backed AI/OCR, or staging alert propagation fails, and passes only when the whole deploy validation unit is complete or when classification proves staging is not required. A green `CI` workflow alone is not sufficient evidence that post-merge delivery passed.
- Automatic main post-merge staging failures create or update one persistent GitHub Issue alert titled `[staging-alert] Post-merge staging deploy failing`. Later failures append comments with the target SHA, run URL, staging URL, job results, and current staging SHA; the next successful staging run comments and closes the issue. This is a CI/deploy visibility alert and does not replace SigNoz/Lark runtime alerting.

**Post-merge staging AI/OCR gate** (`.github/workflows/staging-ai-ocr-gate.yml`):
- Automatic `Staging AI/OCR Gate` execution lives in `.github/workflows/staging-deploy.yml` and starts only after deploy health succeeds in the same serialized post-merge workflow unit.
- `.github/workflows/staging-ai-ocr-gate.yml` remains as a manual recovery entry point via `workflow_dispatch` for rerunning provider-backed validation against the currently selected ref.
- Automatic AI/OCR gates inherit the deploy workflow's successful-main-CI `workflow_run` trigger before spending provider quota. If the matching CI run fails, is cancelled, or times out, automatic staging deploy and real OCR/LLM tests do not run.
- Tests marked `llm` are the only tests allowed to call the configured AI/OCR provider and run once, serially, in this provider-backed gate.
- The automatic gate passes the deployed short SHA as `EXPECTED_SHA`, so version checks still validate the deployed commit before provider-backed parsing starts.
- The automatic gate checks out the full SHA emitted by `build-and-deploy` before setting up E2E tests. This keeps the test code, audit context, and deployed image under validation aligned to the same commit instead of the newest `main` ref.
- The GLM-backed PDF gate allows a longer parsing window than normal UI tests: JSON extraction requests use `AI_JSON_TIMEOUT_SECONDS=360`, and the browser gate waits up to `PARSING_TIMEOUT_MS=480000` so slow but successful `glm-4.6v` PDF parsing is not misclassified as a failed provider gate.
- The serialized GLM gate includes `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_statement_upload_e2e.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, and `tests/e2e/test_personal_financial_report_package.py`. The brokerage test uploads Moomoo and Futu PDF fixtures through `/api/statements/upload`, waits for parsed statements, imports positions through `/api/statements/{id}/brokerage/import`, and verifies `/api/portfolio/holdings` plus `/api/reports/balance-sheet`. The four-asset gate uses an isolated user to combine deterministic bank statement posting, brokerage PDF import, property/mortgage/ESOP manual valuation snapshots, exact as-of net worth, and dashboard/report totals. The personal financial report package gate verifies statements, schedules, notes, restricted-asset treatment, report exports, and source traceability from one fresh user. Failures identify whether OCR parsing, parsed-data state transition, brokerage import, manual valuation, reporting, report packaging, or dashboard aggregation failed. The path-level proof matrix is maintained in [EPIC-017](../project/EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix) with the compact entry-point version in the README; critical product proof anchors live in [critical-proof-matrix.yaml](critical-proof-matrix.yaml). Every `post_merge_environment` proof in that matrix that carries the `llm` marker must appear in both `.github/workflows/staging-deploy.yml` and `.github/workflows/staging-ai-ocr-gate.yml`.

**PR preview E2E** (`.github/workflows/pr-test.yml`):
- PR preview environments do not inject `ZAI_API_KEY`; they validate app wiring without real GLM/OCR provider calls.
- `tools/pr_preview_lifecycle.py` owns PR preview create/update/deploy/delete, PR close cleanup, and scheduled closed-PR reconciliation. The workflow does not hand-roll separate Dokploy lifecycle shell blocks because create, rollback, cleanup, and reconciliation must share the same naming, metadata, logging, and redaction contract.
- PR preview Dokploy API responses are parsed for required fields only. Workflows must not print raw Dokploy response JSON because compose responses can include environment data and refresh tokens.
- Dokploy API and CLI checks may coexist when Dokploy exposes different operational surfaces, but deploy proof must compare only allowlisted effective state differences. The PR preview logged diff is limited to `IMAGE_TAG`, `GIT_COMMIT_SHA`, `IAC_CONFIG_HASH`, `COMPOSE_PROJECT_NAME`, `ENV_SUFFIX`, `ENV_DOMAIN_SUFFIX`, `NEXT_PUBLIC_API_URL`, `DB_HOST`, `S3_HOST`, and `COMPOSE_PROFILES`; unchanged fields and secret-like fields are not printed.
- PR preview deploy builds and pushes commit-scoped PR backend and frontend images in parallel jobs before invoking Dokploy. The preview compose uses `docker-compose.pr-preview.yml` and `IMAGE_TAG=pr-<number>-<github.sha>`, so `finance_report-backend:pr-<number>-<github.sha>` and `finance_report-frontend:pr-<number>-<github.sha>` must both be available in GHCR before `tools/pr_preview_lifecycle.py --action deploy` can trigger the rollout. `tools/pr_preview_lifecycle.py` must initialize and refresh Dokploy as a GitHub-source `docker-compose` app pointing at `docker-compose.pr-preview.yml`; create-time source initialization is required because later source-only updates can be accepted by Dokploy without materializing a deployment. The preview compose source must set `autoDeploy=false`: GitHub Actions is the only rollout owner, and Dokploy push auto-deploy can create a second deployment record after the explicit CI deploy, keeping the compose in `running` after the CI-owned deployment already reached `done`. Reusing a mutable `pr-<number>` image tag is prohibited because Dokploy may continue serving a stale local image. Dokploy PR preview compose commands must run `docker compose up` with `--pull always --no-build` because CI already built the images; letting the single Dokploy deployment worker rebuild PR images can block unrelated preview deployments. The preview compose sets `pull_policy: always`, has no backend/frontend `build:` sections, has no `profiles:`, and does not depend on Dokploy passing `COMPOSE_PROFILES`. It must not rebuild backend or frontend images on the VPS. PR close cleanup deletes GHCR tags with prefix `pr-<number>-` for backend/frontend.
- Existing PR preview composes must preserve the Dokploy compose identity during normal rollout, update the allowlisted deploy environment, and call Dokploy `compose.redeploy` so existing preview environments pull the commit-scoped images again. New preview composes still use `compose.deploy`. The lifecycle must not pre-stop an existing compose on the normal redeploy path: commit-scoped public routes prevent an older container from satisfying newer readiness, and stopping first can disrupt an active Dokploy rollout before Traefik has attached the backend route. The lifecycle must not call Dokploy `compose.start` after `compose.redeploy`: redeploy already queues the rollout, and a second start request can fail independently of the accepted deployment. If `compose.redeploy` returns queued but `compose.one` does not expose a new deployment id within the 600-second worker-queue observation window, or the new deployment id does not reach `done`, the lifecycle fails before readiness as a platform rollout failure. Each observation logs compose status, deployment count, and new deployment ids without raw response bodies. Deployment or compose error summaries may print only allowlisted deployment diagnostic fields such as message, error, errorMessage, status reason, reason, description, and logPath; these values must be truncated and redacted, and raw compose, deployment, and env payloads must not be printed.
- PR preview public routing is commit-scoped: lifecycle code derives `ENV_SUFFIX`, `ENV_DOMAIN_SUFFIX`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_URL`, database/minio host names, and host port offsets from `pr-<number>-<github.sha[:12]>`. The Dokploy compose remains named `pr-<number>` for PR close cleanup, but readiness and E2E must use the `app_url` output written by `tools/pr_preview_lifecycle.py --action deploy`, not a workflow-local `https://report-pr-<number>.<domain>` string. This prevents an older preview container or stale Traefik route from satisfying a newer commit's readiness check.
- PR preview readiness starts only after Dokploy exposes a new deployment record and that record reaches `done`. `running` is an intermediate worker state and must not release readiness because Docker containers and Traefik routes can still be absent for the target SHA. For newly created preview composes, if Dokploy accepts `compose.deploy` but does not expose a deployment record within the short new-record window, CI retries once with `compose.redeploy` before classifying the rollout as a platform failure. Missing or unfinished deployment records are classified as platform rollout failures and should be debugged with infra2's Dokploy Route Canary before app readiness or browser E2E spends time on a stale route. API and frontend readiness remain the final public-route and expected-SHA proof after the rollout record finishes.
- PR preview readiness waits for both `/api/health` and `/frontend-version.json?expected=<sha>` to report the expected `github.sha` before browser E2E starts. API readiness uses a 600-second deadline and logs unbuffered per-attempt route probes for `/api/health`, `/api/ping`, and `/frontend-version.json?expected=<sha>` so failures split into public-route absence, frontend fallback, backend route/health, backend health responses missing `git_sha`/`version`, stale backend SHA, or healthy frontend with missing API route. Each probe line includes elapsed seconds, `app_readiness_classification`, and `platform_failure_domain`; platform-domain values intentionally align with infra2's Dokploy Route Canary (`dokploy-control-plane`, `dokploy-worker-or-deployment-record`, `docker-runtime`, `traefik-public-route`) so a preview failure can be escalated to the platform canary without reinterpreting raw HTTP errors. Readiness probes must use bounded `curl` calls with connect/max-time limits, subprocess timeouts, and an outer workflow step timeout so a healthy public route cannot leave CI stuck in a Python network call. The probes must split response bodies from curl status metadata with an explicit marker rather than a generic trailing newline, send `Accept: application/json`, preserve the full API response body for JSON parsing, and log only the API response content type, body byte count, and a short escaped body prefix when a 200 response is missing `git_sha`/`version`; this makes runner-side parser failures, frontend/edge fallback bodies, and backend health payload gaps distinguishable from the same `route_probe` line without corrupting valid health JSON. Repeated route/backend misses emit a notice after the frontend serves the target SHA, but they must not cut short the full readiness window because backend cold start can lag behind frontend route attachment. App-only states may report `application-runtime` and should stay in this repo. The Traefik API router must have explicit priority above the same-host web router so `/api/*` cannot be shadowed by the frontend route. The frontend image and runtime environment must carry `GIT_COMMIT_SHA`; the frontend readiness request sets a normal `User-Agent` so edge routing does not reject the CI probe before it can read the bundle fingerprint.
- PR preview compose env includes stable metadata: `PR_PREVIEW_PR_NUMBER`, `PR_PREVIEW_COMPOSE_NAME`, `PR_PREVIEW_COMPOSE_PROJECT`, `COMPOSE_PROJECT_NAME`, and `PR_PREVIEW_CREATED_BY=github-actions`. Cleanup uses that deterministic compose project and PR number rather than broad volume pruning.
- PR preview E2E explicitly excludes tests marked `llm`. The post-merge `Staging AI/OCR Gate` workflow is the single automated CI entry point that may spend provider quota.
- PR preview non-LLM E2E mirrors the staging non-LLM command shape: `STRICT_E2E_GATES=true`, marker `(smoke or e2e) and not llm`, and `-n 4` parallelism. The provider-backed `llm` marker remains post-merge only.
- The shared `.github/actions/setup-e2e-tests` action owns E2E Python import setup. It must export the repository root through `PYTHONPATH` via `$GITHUB_ENV` before preview, staging, AI/OCR, or production E2E pytest commands run, because `tests/e2e/conftest.py` imports shared helpers through the `tests.e2e.*` package path while pytest may choose `tests/e2e` as its root directory.
- PR preview cleanup has two lifecycle paths: the PR `closed` event removes the Dokploy stack and GHCR PR images; the scheduled `PR Preview Cleanup` fallback runs only Dokploy compose reconciliation for closed or missing PR previews. GitHub workflows must not SSH to the VPS for PR cleanup. Scheduled reconciliation must not own generic host hygiene, global Docker volume pruning, `docker system prune --volumes`, build-cache pruning, image pruning, or journal vacuuming.
- `tools/cleanup_pr_preview_resources.py` is a deprecated compatibility entry point and must not perform SSH cleanup or host-wide Docker/journal pruning. Closed-PR leftovers use `tools/pr_preview_lifecycle.py --action reconcile`; host hygiene uses the Dokploy server schedule managed by `tools/vps_host_hygiene.py --ensure-dokploy-schedule`.
- PR preview containers created from `docker-compose.yml` use the `json-file` logging driver with bounded `max-size` and `max-file` options so Docker container logs cannot grow without limit between scheduled cleanup runs.
- Generic VPS host hygiene runs as a Dokploy `server` Schedule Job. It prunes old stopped non-preview containers, old build cache, old unused images, all unused Docker networks, oversized Docker json logs, and systemd journal retention. Unused Docker networks are not age-gated because commit-scoped PR preview retries can leave orphan networks that exhaust Docker's predefined address pools before disk age thresholds are reached; Docker will not remove networks attached to running containers. It also removes PR preview Docker containers and compose volumes unless the PR number is among the most recent 3 PRs or the Docker resource was created within the last 3 days. Commit-scoped PR preview container names such as `finance-report-backend-pr-738-<sha12>` must be recognized as preview resources, and preview containers in `restarting`, `exited`, `dead`, `created`, or Docker `unhealthy` state are removed even inside the normal age/recent retention window so orphaned closed-PR runtimes cannot keep the infra watchdog red. This keeps host disk policy independent from GitHub Actions SSH access while still using Dokploy as the operational scheduler.
- GLM/OCR CI traffic uses `AI_BASE_URL=https://api.z.ai/api/coding/paas/v4`; the URL remains an env override so the base provider can be replaced without code changes.

**Production release dry-run** (`.github/workflows/production-release.yml`):
- Manual `workflow_dispatch` with `dry_run=true` verifies the target SHA's successful `main` CI result, runs release lint, and builds production images with `push: false`.
- The dry-run uses production frontend build arguments without changing Dokploy or production tags, and does not enter the `production` environment or push GHCR images. Its summary reports the validated ref/tag and states that production mutation was skipped.
- Tag pushes remain the only automatic path that pushes versioned release images. Manual dispatch with `dry_run=false` remains the production deploy path for an existing version.
- Production backend release images bake `GIT_COMMIT_SHA` from the release tag, and Dokploy deploys also inject the same runtime `GIT_COMMIT_SHA` so `/api/health` can prove the deployed version even after a same-tag redeploy.
- Production deploys run `tools/production_infra_smoke.py` after health check. That gate verifies the deployed version, `/api/health` dependency checks for database and S3, read-only `/api/ping`, frontend reachability, and the shared SigNoz health/version endpoints before production smoke and read-only E2E run.

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
context (`validation_error`, `parsing_progress`, `confidence_score`, and
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

PR preview E2E intentionally excludes the `llm` marker and does not inject the
provider API key. This keeps provider spend and concurrency concentrated in the
post-merge staging job, where `STRICT_E2E_GATES=true` makes provider/config
failures block deploy. PR preview remains useful for app wiring and non-provider
flows without turning provider instability into PR noise.

---

## Related

- [development.md](./development.md) — Moon commands and local setup
- [environments.md](./environments.md) — Six environment overview
- [coverage.md](./coverage.md) — Unified coverage system
- [tdd.md](./tdd.md) — TDD workflow and coverage goals
