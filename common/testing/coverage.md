# Coverage Policy SSOT

> **SSOT Key**: `coverage`  
> **Version**: `4.0.0`  
> **Version scope**: Defines non-blocking CI coverage metric collection and dashboard reporting.

## Metric Collection & Dashboard Reporting

- **Backend**:
  - `apps/backend/pyproject.toml` keeps default `addopts` single-process and coverage-free for fast focused TDD (`pytest -n0 --no-cov -o addopts=`).
  - **PR CI (`pull_request`)**: Backend shards, integration tests, and tooling run with `--no-cov` to meet the PR pipeline time budget.
  - **`main` CI (`push` / `workflow_dispatch`)**: Shards emit `cov-data-*` artifacts across `backend`, `backend-integration`, and `tooling`. The `backend-coverage-gate` job combines them into `coverage-backend-summary.json` for `ci-post-telemetry` and the live quality dashboard (`/board/`), without blocking merges or releases.
- **Frontend**: `apps/frontend/vitest.config.ts` emits `coverage-summary.json` and `lcov.info` for `ci-post-telemetry` and the live quality dashboard without blocking thresholds.

## Source-Root Registration

`apps/backend/pyproject.toml` and `apps/frontend/vitest.config.ts` own coverage inclusion and omission lists; no external exemption registry exists.

## Invariants

- Coverage claims in docs must match generated `ci-post-telemetry` artifacts.
- Coverage jobs report metrics non-blockingly and do not enforce percentage floors.
- Any source omission in `apps/backend/pyproject.toml` requires a documented tracking issue rather than a silent exclusion.
