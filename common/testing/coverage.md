# Coverage Policy SSOT

> **SSOT Key**: `coverage`  
> **Version**: `3.1.0`  
> **Version scope**: Defines CI vs local coverage enforcement boundaries.

## Coverage Floors & Execution Split

- **Backend**:
  - `apps/backend/pyproject.toml` keeps default `addopts` single-process and coverage-free for fast focused TDD (`pytest -n0 --no-cov -o addopts=`).
  - **PR CI (`pull_request`)**: Backend shards, integration tests, and tooling run with `--no-cov` to meet the PR pipeline time budget.
  - **`main` CI (`push` / `workflow_dispatch`)**: Shards emit `cov-data-*` artifacts across `backend`, `backend-integration`, and `tooling`; `backend-coverage-gate` combines them and enforces `--fail-under=96` statement coverage.
  - **Local full check**: `make test-cov` runs explicit branch coverage (`--cov=src --cov-branch --cov-fail-under=96`).
- **Frontend**: `apps/frontend/vitest.config.ts` enforces thresholds `lines/functions/statements 98`, `branches 84`.

## Source-Root Registration

`apps/backend/pyproject.toml` and `apps/frontend/vitest.config.ts` own coverage inclusion/omission lists; no external exemption registry exists.

## Local Verification

```bash
cd apps/backend && uv run pytest -n 4 --cov=src --cov-report=term-missing --cov-branch --cov-fail-under=96
cd apps/frontend && npx vitest run --coverage
```

## Invariants

- Coverage claims in docs must be backed by generated CI artifacts.
- Coverage thresholds must match `apps/backend/pyproject.toml`, `apps/frontend/vitest.config.ts`, and `.github/workflows/ci.yml`.
- Any source omission in `apps/backend/pyproject.toml` requires a documented tracking issue rather than a silent exclusion.
