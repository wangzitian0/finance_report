# CI/CD and Test Optimization SSOT

> **SSOT Key**: `ci-cd`
> **Source of Truth** for CI job structure, test optimization modes, and performance metrics.

*Extracted from [development.md](./development.md) — see that file for Moon commands and local setup.*

---

## CI Job Structure

The GitHub Actions workflow (`.github/workflows/ci.yml`) follows this job dependency order:

```
lint → backend shards → frontend → unified-coverage → finish
```

### Job Details

| Job | Purpose | Dependencies |
|-----|---------|--------------|
| **lint** | Static analysis (ruff check + format check) + manifest/doc checks | None (first job) |
| **backend** (Shards 1-4) | Backend unit + integration tests | `needs: [lint]` |
| **frontend** | Frontend build + tests | None (runs in parallel with backend) |
| **unified-coverage** | Calculate unified coverage, audit source-tree/LCOV policy, compare to baseline, update Coveralls | `needs: [backend, frontend]` |
| **finish** | Aggregate all job results | `needs: [backend, frontend, lint, unified-coverage]` |

### Key CI Properties

1. **Standalone Lint Job**: Runs independently; lint failures surface in ~1 min (not after 10 min backend shard).
2. **Coveralls Upload**: All upload steps have `github-token` authentication. `continue-on-error: true` preserved.
3. **Coverage Policy Audit**: `scripts/check_coverage_policy.py` fails CI if backend, frontend, or script source files drift from their LCOV report.
4. **No-regression gate**: Zero-tolerance; if ANY component is below baseline, CI fails immediately.

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
   - `scripts/check_coverage_policy.py` compares eligible source files with LCOV `SF:` entries
   - `scripts/build_unified_lcov.py` rewrites component-relative LCOV paths to repository-root-relative paths for Coveralls
   - New source modules are automatically required to appear in LCOV unless explicitly excluded by policy

3. **Environment Variables**:
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
- 4-way parallel test sharding via `pytest-split`
- Each shard: `pytest --splits 4 --group N`
- Coverage reports merged post-run
- Coverage policy audited after backend, frontend, and scripts LCOV reports exist
- Coveralls unified upload uses repository-root-relative backend + frontend + scripts LCOV, matching the local unified calculation

**Post-merge staging deploy health gate** (`.github/workflows/staging-deploy.yml`):
- Non-LLM smoke/E2E tests run in parallel with `-n 4`.
- Basic staging deploy feedback no longer waits on provider-backed OCR parsing. Deploy health covers image build/push, Dokploy rollout, `/api/health`, shell smoke checks, and core non-LLM E2E.
- Staging deploys use a workflow-level `staging-deploy` concurrency group with `cancel-in-progress: true`, so stale in-progress staging deploys are cancelled when a newer `main` commit is pushed. Staging tracks the latest `main` commit; older queued deploy validation is not authoritative.
- The staging deploy job has a 30-minute job timeout and the E2E step has a 22-minute E2E step timeout. The E2E command logs `[phase:start]` and `[phase:end]` records for smoke and core non-LLM E2E so timeout and latency failures identify the active phase.
- Staging deploys may set `DEPLOY_PRIMARY_MODEL_OVERRIDE`, `DEPLOY_OCR_MODEL_OVERRIDE`, and `DEPLOY_VISION_MODEL_OVERRIDE`; the current post-merge gate pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v`.
- Repeated `/api/health` 404 responses are treated as route failures, not generic backend failures: the health script probes `/api/ping` and `/` so logs distinguish a missing or shadowed Traefik API route from an unhealthy backend container.

**Post-merge staging AI/OCR gate** (`.github/workflows/staging-ai-ocr-gate.yml`):
- `Staging AI/OCR Gate` runs automatically after `Deploy Staging` completes successfully on `main`, and can also be triggered manually via `workflow_dispatch`.
- The workflow uses a global `staging-ai-ocr` concurrency group with `cancel-in-progress: true` because staging is a singleton environment and only the newest provider-backed validation is authoritative.
- Tests marked `llm` are the only tests allowed to call the configured AI/OCR provider and run once, serially, in this separate provider-backed gate.
- The gate checks out the same `workflow_run.head_sha` that deployed to staging and passes its short SHA as `EXPECTED_SHA`, so version checks still validate the deployed commit.
- The GLM-backed PDF gate allows a longer parsing window than normal UI tests: JSON extraction requests use `AI_JSON_TIMEOUT_SECONDS=360`, and the browser gate waits up to `PARSING_TIMEOUT_MS=480000` so slow but successful `glm-4.6v` PDF parsing is not misclassified as a failed provider gate.
- The serialized GLM gate includes `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_statement_upload_e2e.py`, and `tests/e2e/test_brokerage_upload_to_portfolio_value.py`. The brokerage test uploads Moomoo and Futu PDF fixtures through `/api/statements/upload`, waits for parsed statements, imports positions through `/api/statements/{id}/brokerage/import`, and verifies `/api/portfolio/holdings` plus `/api/reports/balance-sheet`. Failures identify whether OCR parsing, parsed-data state transition, brokerage import, portfolio valuation, or reporting failed.

**PR preview E2E** (`.github/workflows/pr-test.yml`):
- PR preview environments do not inject `ZAI_API_KEY`; they validate app wiring without real GLM/OCR provider calls.
- PR preview E2E explicitly excludes tests marked `llm`. The post-merge `Staging AI/OCR Gate` workflow is the single automated CI entry point that may spend provider quota.
- GLM/OCR CI traffic uses `AI_BASE_URL=https://api.z.ai/api/coding/paas/v4`; the URL remains an env override so the base provider can be replaced without code changes.

> **Local vs GitHub CI Parallelism**
>
> | Environment | Parallelism | Test Scope | Resource Usage |
> |-------------|-------------|------------|----------------|
> | **GitHub CI** | `-n auto` + `--splits 4` | ~25% tests per shard | Low (ephemeral runners) |
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

`tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value`
is the upload-to-report portfolio hard gate for Issue #404. It proves that at
least two brokerage PDFs can be parsed by the real configured OCR path, imported
as portfolio positions, and reflected in the latest balance-sheet asset value.

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
