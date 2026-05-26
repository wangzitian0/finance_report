# CI/CD and Test Optimization SSOT

> **SSOT Key**: `ci-cd`
> **Source of Truth** for CI job structure, test optimization modes, and performance metrics.

*Extracted from [development.md](./development.md) — see that file for Moon commands and local setup.*

---

## CI Job Structure

The GitHub Actions workflow (`.github/workflows/ci.yml`) follows this job dependency order:

```
classify-changes → backend shards + frontend → unified-coverage → finish
               ↘ lint ─────────────────────────────────────↗
               ↘ ac-traceability ──────────────────────────↗
```

### Job Details

| Job | Purpose | Dependencies |
|-----|---------|--------------|
| **classify-changes** | Detect whether changed paths require heavy backend/frontend/coverage jobs | None |
| **lint** | Static analysis (ruff check + format check) + manifest/doc checks | None (first job) |
| **backend** (Shards 1-6) | Backend unit + integration tests when heavy CI is required | `needs: [classify-changes]` |
| **frontend** | Frontend build + tests when heavy CI is required | `needs: [classify-changes]` |
| **container-images** | Build backend and frontend staging images without pushing on PRs; push SHA-tagged images only on `main` | `needs: [classify-changes]` |
| **unified-coverage** | Calculate unified coverage, audit source-tree/LCOV policy, compare to baseline, update Coveralls when heavy CI is required | `needs: [classify-changes, backend, frontend]` |
| **ac-traceability** | Verify AC-to-test traceability for all PR/main changes, including docs-only changes | None |
| **finish** | Aggregate all required and skipped job results | `needs: [classify-changes, backend, frontend, container-images, lint, unified-coverage, ac-traceability]` |

### Key CI Properties

1. **Standalone Lint Job**: Runs independently; lint failures surface in ~1 min (not after 10 min backend shard).
2. **Change Classification**: Lightweight documentation, issue-template, markdown, and `.github/workflows/docs.yml` changes skip backend, frontend, and unified coverage. Runtime, test, script, CI, dependency, and coverage-policy changes run the full heavy path.
3. **Stable Required Checks**: Heavy jobs are skipped through job-level conditions rather than removing the workflow, so required check names remain visible and mergeable.
4. **AC Traceability Always Runs**: AC traceability is separate from unified coverage so docs-only AC/EPIC changes still get traceability validation. The job first runs `scripts/generate_ac_registry.py --check` to ensure EPIC-defined ACs are registered without rewriting historical registry descriptions, then runs `scripts/check_ac_traceability.py` as the fail-closed gate, then generates `AC-TEST-TRACEABILITY-AUDIT.md` into `$RUNNER_TEMP`; the audit is uploaded as a CI artifact. The audit distinguishes real test references from `_ac_stubs`, trivial placeholder assertions, pure `pass`, and pure skipped tests. CI fails on mandatory AC coverage that is missing, placeholder-only, or stub-only; full-strikethrough deprecated ACs are excluded from the mandatory gate. CI does not fail solely because the checked-in archive copy is stale.
5. **Coveralls Upload Is Reporting-Only**: Unified, backend, and frontend Coveralls uploads run on both pull requests and `main` pushes when heavy CI is required. CI pass/fail is decided by local gates (`scripts/check_ci_metrics_contract.py`, `scripts/check_coverage_policy.py`, `scripts/calculate_unified_coverage.py`); Coveralls upload remains enabled for dashboards and history but does not block merges or post-merge staging.
6. **Single CI Metrics Contract**: `scripts/check_ci_metrics_contract.py` is the single CI metrics contract. It validates that source-root discovery, `scripts/coverage_policy.py`, workflow gates, and AC traceability semantics stay aligned before coverage is calculated.
7. **Toolchain Contract**: `scripts/check_toolchain_contract.py` runs in lint and fails when Python, Node.js, uv, Docker base images, Compose service images, or frontend engine constraints drift from `toolchain.toml`.
8. **PR Image Build Validation**: PR CI dry-runs staging image builds before merge with the same Dockerfiles, contexts, and build arguments used by `main`. Main push CI is the only path that pushes SHA-tagged images to GHCR.
9. **Coverage Policy Audit**: `scripts/check_coverage_policy.py` fails CI if backend, frontend, or script source files drift from their LCOV report.
10. **No-regression gate**: Zero-tolerance; if ANY component is below baseline, CI fails immediately.

### PR vs Main CI Responsibilities

Pull requests run the same heavy CI path as `main` when runtime, tests, scripts,
CI, dependency, or coverage-policy files change. This keeps branch protection
strict before merge.

Pushes to `main` still run heavy CI for runtime changes even though the merged PR
already ran required checks. The retained post-merge run provides two signals
that PR checks cannot fully replace: validation of the exact merge commit and a
final local gate before post-merge staging/AI workflows consume the new commit.
Coverage regression detection is enforced locally against
`unified-coverage.json`; Coveralls remains reporting-only and does not decide CI
pass/fail.

Lightweight changes do not repeat the heavy path on either PRs or `main`.
Lightweight means all changed files are limited to documentation, markdown,
issue templates, or `.github/workflows/docs.yml`. Other workflow changes are not
skipped because they may affect CI, deploy, or release behavior and must exercise
the full gate.

### Proof Placement Policy

The test system separates proof by where the failure can be acted on:

| Proof type | Runs where | Purpose |
|---|---|---|
| Behavioral tests | PR CI before merge | Prove deterministic product behavior, accounting invariants, API contracts, frontend flows, and script/tool contracts before code enters `main`. |
| Environment gates | Post-merge deploy workflows | Prove the exact merged SHA can run in staging/production-like environments with real routing, Vault/Dokploy/GHCR/SigNoz wiring, deployed images, and provider-backed OCR/LLM credentials. |
| Reference traceability | PR and `main` CI | Prove every mandatory AC has a real non-placeholder test reference; this is not behavioral coverage by itself. |

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
   - Compares current vs baseline for **all components**: unified, backend, frontend, scripts
   - Uses `round(x, 2)` for floating-point comparison
   - **Zero tolerance**: `current < baseline` → CI fails immediately
   - If baseline file missing: falls through to `COVERAGE_THRESHOLD` check (safety net)
3. **Source-tree/LCOV Logic**:
   - `scripts/coverage_policy.py` defines the single component policy used by coverage calculation and audit checks
   - `scripts/check_ci_metrics_contract.py` first discovers source roots and fails CI when a new `apps/*/src` or `packages/*/src` source root is not represented in `scripts/coverage_policy.py`
   - `scripts/check_coverage_policy.py` compares eligible source files with LCOV `SF:` entries
   - `scripts/build_unified_lcov.py` rewrites component-relative LCOV paths to repository-root-relative paths for Coveralls
   - New source modules are automatically required to appear in LCOV unless explicitly excluded by policy
   - New `apps/*/src` or `packages/*/src` source roots fail CI until they are added to the coverage policy and report pipeline

4. **Metric Semantics**:
   - Line coverage is the only numeric source coverage metric enforced by the no-regression gate
   - AC traceability is a reference metric, not behavioral coverage
   - AC traceability fails missing, placeholder-only, and `_ac_stubs`-only mandatory AC references
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

**Scripts**:
- `scripts/get_changed_files.py` — Detects changed Python files via git diff
- `scripts/smart_test.py` — Runs all tests, coverage on changed files only
- `scripts/fast_test.py` — Runs all tests, no coverage
- `scripts/test_lifecycle.py` — DB lifecycle (accepts coverage flags from callers)

**CI Optimization** (`.github/workflows/ci.yml`):
- Change classification is implemented in `scripts/ci_change_classifier.py` and skips backend/frontend/unified coverage for lightweight docs and docs workflow changes.
- PR preview environments deploy only for app, compose, E2E, or preview-action changes. Traceability tooling, docs, and non-preview workflow changes still run CI and AC gates without consuming a Dokploy preview slot.
- Markdown outside the documented lightweight trees is treated as heavy; this prevents runtime-adjacent README or script documentation changes from being hidden by a global `*.md` skip.
- Backend shards and AC traceability run in parallel with lint once change classification has finished, so lint remains visible without delaying independent test work.
- 6-way parallel test sharding via `pytest-split`
- Each shard: `pytest --splits 6 --group N`
- Coverage reports merged post-run
- Coverage policy audited after backend, frontend, and scripts LCOV reports exist
- Coveralls unified upload uses repository-root-relative backend + frontend + scripts LCOV, matching the local unified calculation.
- CI keeps Coveralls uploads enabled after local coverage gates pass; external Coveralls status is informational and does not block `unified-coverage` job success.
- CI calls `scripts/check_toolchain_contract.py` in lint before dependency installation. Runtime versions and base images are owned by `toolchain.toml`, mirrored to local tool-manager files, and used by GitHub Actions, Dockerfiles, and `docker-compose.yml`.
- PR CI dry-runs staging image builds before merge. The `container-images` job uses `docker/build-push-action` for both backend and frontend images with `push: false` on pull requests, then `finish` fails if that validation job fails.
- Main push CI is the only path that pushes SHA-tagged images. Registry login and image push are guarded by `github.event_name == 'push' && github.ref == 'refs/heads/main'`; registry availability and authorization remain post-merge external-service risks, but Dockerfile, build-context, and build-argument errors are caught before merge.
- Frontend dependency installation uses `actions/setup-node@v4` with npm cache and deterministic `npm ci`.
- The `finish` job appends a GitHub Step Summary from `scripts/github_workflow_timing_summary.py` with queue delay, execution window, run wall time, longest completed job, and per-job durations.
- Coveralls uploads are reporting-only and do not block CI pass/fail when local deterministic gates pass.

**Checked-in AC traceability archive** (`docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md`):
- This file is a historical/manual snapshot, not the current CI source of truth.
- Routine PRs should not refresh it solely because ACs or test references changed; the current audit is generated in CI and uploaded as the `ac-test-traceability-audit` artifact.
- Refresh the checked-in archive only for an intentional documentation snapshot/release, otherwise it creates unnecessary merge conflicts across parallel PRs.

**Post-merge staging deploy health gate** (`.github/workflows/staging-deploy.yml`):
- Non-LLM smoke/E2E tests run in parallel with `-n 4`.
- The shared E2E setup action caches `.venv` and Playwright browsers so staging, manual AI/OCR, PR preview, and production smoke runs do not repeatedly download identical E2E dependencies.
- PR CI validates backend and frontend staging image builds without pushing so Dockerfile, context, and build-argument errors are blocked before merge. Main push CI builds and pushes SHA-tagged staging images in parallel with tests when heavy CI is required. These images are immutable commit artifacts and do not move the live `staging` tag.
- Staging deploy waits for the same commit's `CI` push workflow to complete successfully before promoting images, pushing `staging` tags, or changing the Dokploy staging environment. If matching CI fails, is cancelled, or times out, staging is not overwritten.
- After same-SHA CI passes, post-merge staging first looks up the backend and frontend SHA-tagged staging images from GHCR. If a SHA image is missing, the workflow falls back to building only the missing image. Once both SHA images are present, staging retags those immutable images as `staging` before deploy. This keeps deploy detection strict while moving normal image build time out of the serialized post-merge lane.
- Deploy health covers image build/push, Dokploy rollout, `/api/health`, shell smoke checks, and core non-LLM E2E.
- Automatic provider-backed AI/OCR validation runs as a downstream job in the same serialized post-merge workflow unit. This keeps staging stable for the SHA under validation: a newer deploy cannot overwrite staging while an older automatic AI/OCR gate is running.
- Staging deploys use a workflow-level `staging-post-merge-${{ github.ref }}` concurrency group with `cancel-in-progress: false`, so GitHub Actions does not cancel a running post-merge lane when a newer `main` commit is pushed. Because GitHub concurrency allows at most one running and one pending run per group, the latest pending post-merge run is retained and older pending runs may be replaced. This is latest-pending serial validation, not strict FIFO for every SHA.
- The staging deploy-health job has a 75-minute deploy-health job timeout and the E2E step has a 22-minute E2E step timeout. The E2E command logs `[phase:start]` and `[phase:end]` records for smoke and core non-LLM E2E so timeout and latency failures identify the active phase.
- The automatic AI/OCR job has a 30-minute job timeout, while the provider-backed pytest step remains capped at 22 minutes.
- Staging deploys may set `DEPLOY_PRIMARY_MODEL_OVERRIDE`, `DEPLOY_OCR_MODEL_OVERRIDE`, and `DEPLOY_VISION_MODEL_OVERRIDE`; the current post-merge gate pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v`.
- Repeated `/api/health` 404 responses are treated as route failures, not generic backend failures: the health script probes `/api/ping` and `/` so logs distinguish a missing or shadowed Traefik API route from an unhealthy backend container.
- The post-merge workflow appends a GitHub Step Summary after deploy health and AI/OCR finish, making queue time, serial execution time, and slow jobs visible without manually scraping logs.

**Post-merge staging AI/OCR gate** (`.github/workflows/staging-ai-ocr-gate.yml`):
- Automatic `Staging AI/OCR Gate` execution lives in `.github/workflows/staging-deploy.yml` and starts only after deploy health succeeds in the same serialized post-merge workflow unit.
- `.github/workflows/staging-ai-ocr-gate.yml` remains as a manual recovery entry point via `workflow_dispatch` for rerunning provider-backed validation against the currently selected ref.
- Automatic AI/OCR gates inherit the deploy workflow's same-SHA CI wait before spending provider quota. If the matching CI run fails, is cancelled, or times out, the staging deploy workflow fails before calling real OCR/LLM tests or changing staging.
- Tests marked `llm` are the only tests allowed to call the configured AI/OCR provider and run once, serially, in this provider-backed gate.
- The automatic gate passes the deployed short SHA as `EXPECTED_SHA`, so version checks still validate the deployed commit before provider-backed parsing starts.
- The GLM-backed PDF gate allows a longer parsing window than normal UI tests: JSON extraction requests use `AI_JSON_TIMEOUT_SECONDS=360`, and the browser gate waits up to `PARSING_TIMEOUT_MS=480000` so slow but successful `glm-4.6v` PDF parsing is not misclassified as a failed provider gate.
- The serialized GLM gate includes `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_statement_upload_e2e.py`, and `tests/e2e/test_brokerage_upload_to_portfolio_value.py`. The brokerage test uploads Moomoo and Futu PDF fixtures through `/api/statements/upload`, waits for parsed statements, imports positions through `/api/statements/{id}/brokerage/import`, and verifies `/api/portfolio/holdings` plus `/api/reports/balance-sheet`. Failures identify whether OCR parsing, parsed-data state transition, brokerage import, portfolio valuation, or reporting failed. The path-level proof matrix is maintained in [EPIC-017](../project/EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix) with the compact entry-point version in the README.

**PR preview E2E** (`.github/workflows/pr-test.yml`):
- PR preview environments do not inject `ZAI_API_KEY`; they validate app wiring without real GLM/OCR provider calls.
- PR preview E2E explicitly excludes tests marked `llm`. The post-merge `Staging AI/OCR Gate` workflow is the single automated CI entry point that may spend provider quota.
- PR preview cleanup has two paths: the PR `closed` event removes the Dokploy stack, volumes, and GHCR PR images; the scheduled `PR Preview Cleanup` fallback removes stale VPS preview containers/compose volumes for closed or missing PRs and prunes aged Docker build cache/images without touching open PR previews.
- GLM/OCR CI traffic uses `AI_BASE_URL=https://api.z.ai/api/coding/paas/v4`; the URL remains an env override so the base provider can be replaced without code changes.

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

- Backend line coverage: **≥ 90%** (enforced by `pytest-cov`)
- Unified coverage: **no-regression from `unified-coverage.json`** (currently 94.38% floor after AC8.13.15 policy unification)
- Branch coverage: Required (via `--cov-branch`)
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
- Unified coverage: **~42s**, including scripts coverage and reporting-only Coveralls uploads.
- The timing summary reports queue delay separately from execution time so future regressions can distinguish runner capacity from workflow critical-path changes.

**Post-merge staging (2026-05-20 observed baseline):**
- Build and deploy job execution: **~5m 19s**.
- Automatic AI/OCR gate execution: **~4m 38s**.
- AI/OCR `Setup E2E Tests`: **~2m 54s** before E2E virtualenv and Playwright browser caching.

**Post-merge staging image promotion (2026-05-21 target):**
- Main push CI owns SHA-tagged staging image creation for heavy runtime changes.
- The serialized staging lane promotes existing SHA images to the moving `staging` tag after same-SHA CI success, avoiding redundant Docker builds in the normal path.
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

## Smoke Tests (`scripts/smoke_test.sh`)

```bash
# Local (after starting servers)
bash scripts/smoke_test.sh

# Against staging/prod
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh
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
| Staging | Shell smoke | `bash scripts/smoke_test.sh "$APP_URL" staging` | No skips; any failed check fails deploy |
| Staging | Non-LLM E2E | `STRICT_E2E_GATES=true pytest tests/e2e -v -m "(smoke or e2e) and not llm" -n 4` | Tests marked `critical` must fail instead of skip |
| Staging | AI/OCR E2E | `STRICT_E2E_GATES=true pytest tests/e2e/test_statement_full_journey.py tests/e2e/test_brokerage_upload_to_portfolio_value.py tests/e2e/test_statement_upload_e2e.py -v -m "llm"` | Serial provider-backed GLM gate; `rejected` fails deploy |
| Production | Shell smoke | `bash scripts/smoke_test.sh https://report.zitian.party production` | Read-only checks only |
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
