# CI/CD and Test Optimization SSOT — Test-Pipeline Half

> **SSOT Key**: `ci-cd` | Merge-time CI pipeline (`.github/workflows/ci.yml`). Deploy half: [common/runtime/ci-cd.md](../runtime/ci-cd.md).

## CI Job Structure

`.github/workflows/ci.yml` runs `lint` in parallel with `changes`:
- `changes` fans out to `schema-migrations`, `backend` (seeded file shards), `backend-integration`, `frontend-build`, `frontend-vitest`, `frontend-playwright`, `frontend-telemetry-e2e`, `tooling` (`tests/tooling/`), and `container-images` (`push` only on main/release push or `workflow_dispatch`; PR CI dry-runs staging image builds before merge when `image_build_required=true`).
- `main`-only `container-images -> verify-sha-image-published` verifies the `:<sha>` tag digest in GHCR.
- `finish` aggregates all jobs and appends the `Pipeline time contract` summary via `tools/github_workflow_timing_summary.py`.

### Env x Stage Contract

`ci-cd` separates environment taxonomy, pipeline stages, and GitHub Actions jobs; not every environment runs every pipeline stage.

#### Environment Axis

- `local`: developer workstation (`moon run :test`, `tools/preflight.py`)
- `pr`: GitHub PR/main CI runner proof before merge
- `staging`: post-merge deployed environment for `main` SHAs (`workflow_dispatch`)
- `prd`: production release environment

#### Pipeline Stage Axis

- `Changed/Affected UT`, `Lint/Static`, `Full UT`, `Integration`, `Regression/E2E`, `Image Build`, `Deploy Smoke`, `Provider Gate`, `Release Integrity`

#### Env x Stage Execution Matrix

Local runs are fast advisory gates; PR CI is the deterministic merge authority; staging and production are deployed-environment proof gates.

### Path Risk to Local Gate Matrix

Default local verification uses `moon run :test -- --smart` or focused Vitest/tooling checks; risk-triggered escalation adds:
- `accounting, posting, reconciliation, money, balance`: focused domain pytest suite
- `schema, migrations`: `alembic upgrade head` + `alembic check` + DB tests
- `API contract, OpenAPI`: backend API tests + `tools/preflight.py` (`api-reference`, `router-contract`)
- `shared common/ / tools/`: `pytest tests/tooling/`
- `Docker, workflow, environment, deploy`: static contract checks (runtime proof in PR CI/staging)
- `docs-only`: static SSOT/manifest checks

### Coverage & Metric Semantics

- Coverage thresholds and deny-list omissions live in `apps/backend/pyproject.toml` (`--cov-fail-under=96` BE) and `apps/frontend/vitest.config.ts` (`98/98/84/98` FE).
- PR CI dry-runs staging image builds before merge; Main and release-branch push CI, plus on-demand `workflow_dispatch` push immutable `:<sha>` images.
- CI observability artifacts (JUnit XML, coverage, run context) upload on both success and failure (`if: always()`).
- Local pytest/Vitest thresholds govern line/branch floors (`--cov-fail-under=96` BE; Vitest `98/98/84/98` FE).

## PR Review Thread Merge Gate

`tools/check_pr_review_threads.py` (run in `lint` on PRs) exits 1 if any unresolved review thread matches `\b(P0|P1)\b` or is authored by `copilot`, `github-copilot[bot]`, `copilot-pull-request-reviewer`, or `copilot-pull-request-reviewer[bot]` without `P2`/`P3`/`nit`. Resolved and outdated threads, plus lower-severity unresolved threads, do not block.

## Test Optimization

- Backend shards use `tools/backend_shard_files.py` (`--splitting-algorithm=least_duration` over `apps/backend/ci/backend-test-durations.json`), with `--cov-fail-under=0` per shard.
- Provider-free journeys use seeded fixtures (`@pytest.mark.e2e` without `@pytest.mark.llm`).
- Related: [development.md](../meta/development.md) · [environments.md](../runtime/environments.md) · [coverage.md](./coverage.md) · [tdd.md](./tdd.md) · [common/runtime/ci-cd.md](../runtime/ci-cd.md)
