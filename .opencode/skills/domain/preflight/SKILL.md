---
name: preflight
description: Run the project's gate checks that are relevant to the current diff BEFORE committing or pushing. Use this whenever you have edited files and are about to commit/push, or after editing EPIC/AC docs, SSOT docs, Pydantic schemas, Alembic migrations, .env files, backend services, the frontend, config.py, or tooling — so CI-style failures surface locally instead of after a push.
---

# Preflight — diff-aware local gates

This repo enforces strict gates in CI/pre-commit (EPIC→AC→test traceability, SSOT
ownership, doc-nav consistency, schema contracts, migration risk, env-key
consistency, ruff, the transaction-boundary meta-test, the env-reference drift
check, the tooling contract tests, and the frontend lint/coverage/build gates).
Forgetting which one a change needs is how failures slip through to CI. Preflight
maps your **changed files** to the relevant gates and runs only those.

## Use it before every commit/push

```bash
# Run inside an interpreter that has project deps (the backend venv):
apps/backend/.venv/bin/python tools/preflight.py          # run relevant gates
apps/backend/.venv/bin/python tools/preflight.py --list   # show what would run
apps/backend/.venv/bin/python tools/preflight.py --base origin/main
```

Exit code is non-zero if any gate fails; the summary names which one.

## What it maps (changed path → gate)

| You touched | It runs |
|---|---|
| `docs/project/EPIC*.md`, `docs/ac_registry*.yaml`, `docs/infra_registry*.yaml` | `generate_ac_registry.py` → `check_ac_traceability.py` |
| `docs/ssot/*` | `check_ssot_ownership.py`, `check_manifest.py` |
| `docs/*`, `mkdocs.yml`, `vision.md`, `README.md` | `lint_doc_consistency.py` |
| `apps/backend/*schema*.py` | `validate_schemas.py` |
| `apps/backend/migrations/*` | `check_migration_risk.py` |
| `.env*` | `check_env_keys.py` |
| `apps/backend/*.py` | `ruff check` + `ruff format --check` |
| `apps/backend/src/config.py` | `generate_env_reference.py --check` (.env.example / env-reference drift) |
| `apps/backend/src/services/*.py` | `test_transaction_boundaries.py` |
| `tools/*`, `common/*` | `pytest tests/tooling/` (tool-wrapper sys.path contract + dispatchers) |
| `apps/frontend/*` | `npm run lint` + `npm run test:coverage` + `npm run build` |

It includes **untracked** files, so new files are checked before they are
committed. The mapping lives in `common/ssot/preflight.py` (`CHECKS`); add a new
gate there with a test in `tests/tooling/test_preflight.py`.

## Notes

- Preflight does **not** replace CI — it mirrors a subset, scoped to the diff, for
  fast local feedback.
- It never runs destructive tools (purge/cleanup/deploy). Those stay manual.
- For an EPIC/AC change specifically, see the **ac-workflow** skill for the full
  EPIC→AC→test ritual that preflight's `ac-traceability` gate verifies.
- The `backend-format` gate runs `ruff` from your **PATH**, not the project-pinned
  one. If your PATH ruff is a different version than the repo pins
  (`apps/backend/.venv/bin/ruff --version`), it can report false-positive format
  failures on files **outside your diff**. CI uses the pinned version, so when
  `backend-format` flags a file you didn't touch, re-check with
  `apps/backend/.venv/bin/ruff format --check src tests` before assuming it's real.
