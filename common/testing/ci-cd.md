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

Default local verification uses fast focused tests (`pytest -n0 --no-cov -o addopts= <file>::<test> -x`, focused Vitest, or `moon run :test -- --fast`) plus cached static `tools/preflight.py` on push; risk-triggered escalation adds:
- `accounting, posting, reconciliation, money, balance`: focused domain pytest suite
- `schema, migrations`: `alembic upgrade head` + `alembic check` + DB tests
- `API contract, OpenAPI`: backend API tests + `tools/preflight.py` (`api-reference`, `router-contract`)
- `shared common/ / tools/`: `pytest tests/tooling/`
- `Docker, workflow, environment, deploy`: static contract checks (runtime proof in PR CI/staging)
- `docs-only`: static SSOT/manifest checks

### Coverage & Metric Semantics

- Coverage thresholds and deny-list omissions live in `apps/backend/pyproject.toml` (`96%` BE floor) and `apps/frontend/vitest.config.ts` (`98/98/84/98` FE).
- On PRs, `backend`, `backend-integration`, and `tooling` run with `--no-cov` for fast `Pipeline time contract` turnaround; on `main` pushes and manual runs, `backend-coverage-gate` combines `.coverage.*` shards across those three lanes and enforces `--fail-under=96`.
- PR CI dry-runs staging image builds before merge; Main and release-branch push CI, plus on-demand `workflow_dispatch` push immutable `:<sha>` images.
- CI observability artifacts (JUnit XML, run context, and non-PR coverage) upload on both success and failure (`if: always()`).
- Local `make test-cov` and Vitest govern full line/branch floors (`--cov-fail-under=96` BE; Vitest `98/98/84/98` FE).

## PR Review Thread Merge Gate

`tools/check_pr_review_threads.py` (run in `lint` on PRs) scores unresolved, non-outdated review threads by literal `severity:` label (`high = 1.0`, `middle`/`medium = 0.5`, `low = 0.25`, unlabelled = `0.5`) and exits 1 when the total score is `>= 1.0`. Resolved and outdated threads do not count, and Copilot review is optional and non-blocking (no special author rule).

## Test Optimization

- Backend shards use `tools/backend_shard_files.py` (`--splitting-algorithm=least_duration` over `apps/backend/ci/backend-test-durations.json`), running `--no-cov` on PRs and emitting `.coverage.shard-*` on `main`.
- Provider-free journeys use seeded fixtures (`@pytest.mark.e2e` without `@pytest.mark.llm`).
- Related: [development.md](../meta/development.md) · [environments.md](../runtime/environments.md) · [coverage.md](./coverage.md) · [tdd.md](./tdd.md) · [common/runtime/ci-cd.md](../runtime/ci-cd.md)
