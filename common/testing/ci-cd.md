# CI/CD and Test Optimization SSOT — Test-Pipeline Half

> **SSOT Key**: `ci-cd` | Merge-time CI pipeline (`.github/workflows/ci.yml`). Deploy half: [common/runtime/ci-cd.md](../runtime/ci-cd.md).

## CI Job Structure

`.github/workflows/ci.yml` runs `changes` then fans out to `lint` and the test lanes:
- `changes` fans out to `lint`, `schema-migrations`, `backend` (seeded file shards), `backend-integration`, `frontend-build`, `frontend-vitest`, `frontend-playwright` (provider-free UI + telemetry emission), `tooling` (`tests/tooling/`), and `container-images` (`push` only on main push or `workflow_dispatch`; PR CI dry-runs staging image builds before merge when `image_build_required=true`).
- On PRs, `backend_required=false` skips `schema-migrations`, `backend`, and `backend-integration` for pure `apps/frontend/` changes, `vitest_required=false` skips `frontend-vitest` for pure `apps/backend/` changes, `frontend_changed=false` skips frontend `npm ci` + `npm run lint` inside `lint`, and `tooling` runs only for shared, CI, reference-doc, or tooling paths.
- `frontend-playwright` reuses the `.next` tarball artifact from `frontend-build` (and builds only when `frontend-build` skips on main push or manual dispatch).
- `main`-only `container-images -> verify-sha-image-published` verifies the `:<sha>` tag digest in GHCR.
- `finish` aggregates all jobs, appends the `Pipeline time contract` summary (derived from `infra2_sdk.manifests.CELL_POLICIES` via `common.testing.github_workflow_timing_summary`), and uploads non-blocking `ci-post-telemetry` artifacts via `common.testing.ci_telemetry`.

### Env x Stage Contract

`ci-cd` separates environment taxonomy, pipeline stages, and GitHub Actions jobs; not every environment runs every pipeline stage.

#### Environment Axis

- `local`: developer workstation (focused single-process test, `python -m common.testing.preflight`)
- `pr`: GitHub PR/main CI runner proof before merge
- `staging`: post-merge deployed environment for `main` SHAs (`workflow_dispatch`)
- `prd`: production release environment

#### Pipeline Stage Axis

- `Changed/Affected UT`, `Lint/Static`, `Full UT`, `Integration`, `Regression/E2E`, `Image Build`, `Deploy Smoke`, `Provider Gate`, `Release Integrity`

#### Env x Stage Execution Matrix

Local runs are fast advisory gates; PR CI is the deterministic merge authority; staging and production are deployed-environment proof gates.

### Path Risk to Local Gate Matrix

Local verification is one command: the focused single-process test of the change (`pytest -n0 --no-cov -o addopts= <file>::<test> -x`). `git push` runs the cached static `python -m common.testing.preflight` gates. CI runs each suite.

### Coverage & Metric Semantics

- Coverage inclusion/omission lists live in `apps/backend/pyproject.toml` and `apps/frontend/vitest.config.ts`; neither enforces blocking percentage floors.
- On PRs, `backend`, `backend-integration`, `tooling`, and `frontend-vitest` run without coverage for fast `Pipeline time contract` turnaround; on `main` pushes and manual runs, `backend-coverage-gate` combines `cov-data-*` across backend/tooling lanes and `frontend-vitest` uploads Vitest coverage, reporting metrics non-blockingly into `ci-post-telemetry` for the live `/board/` dashboard.
- PR CI dry-runs staging image builds before merge; Main push CI, plus on-demand `workflow_dispatch` push immutable `:<sha>` images.
- CI observability artifacts (JUnit XML, run context, and non-PR coverage) upload on both success and failure (`if: always()`).

## PR Review Thread Merge Gate

`python -m common.testing.check_pr_review_threads` (run in `lint` on PRs) scores unresolved, non-outdated review threads by literal `severity:` label (`high = 1.0`, `middle`/`medium = 0.5`, `low = 0.25`, unlabelled = `0.5`) and exits 1 when the total score is `>= 1.0`. Resolved and outdated threads do not count, and Copilot review is optional and non-blocking (no special author rule).

## Test Optimization

- Backend shards use `python -m common.testing.backend_shard` (`--splitting-algorithm=least_duration` over `apps/backend/ci/backend-test-durations.json`), running `--no-cov` on PRs and emitting `cov-data-shard-*` on `main`.
- Provider-free journeys use seeded fixtures (`@pytest.mark.e2e` without `@pytest.mark.llm`).
- Related: [development.md](../meta/development.md) · [environments.md](../runtime/environments.md) · [coverage.md](./coverage.md) · [tdd.md](./tdd.md) · [common/runtime/ci-cd.md](../runtime/ci-cd.md)
