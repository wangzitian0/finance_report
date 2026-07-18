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
apps/backend/.venv/bin/python tools/preflight.py                # run relevant gates
apps/backend/.venv/bin/python tools/preflight.py --tier=static  # seconds-level pre-push parity set
apps/backend/.venv/bin/python tools/preflight.py --list         # show what would run (with each check's tier)
apps/backend/.venv/bin/python tools/preflight.py --base origin/main
```

Exit code is non-zero if any gate fails; the summary names which one.

## Tiers (#1810)

Every check carries a cost tier; `--tier` composes with the diff-glob
selection (it narrows the selected set, never widens it):

- `--tier=static` — only the seconds-level file-parser gates: the mandatory
  pre-push parity set (AGENTS.md § Pre-Push Gate Parity).
- `--tier=heavy` — only the expensive suite/build gates (the `tests/tooling/`
  pytest suite, ~3 min; the frontend lint+coverage+build chain).
- `--tier=full` (default) — both tiers, exactly the pre-tier behavior.

Interactive operators run `--tier=static` before every push at minimum;
cloud/sandbox agents run the default full tier before pushing (their CPU does
not contend with the operator's machine).

## What it maps (changed path → gate)

| You touched | It runs |
|---|---|
| `docs/project/EPIC*.md`, `docs/ac_registry*.yaml`, `docs/infra_registry*.yaml` | `generate_ac_registry.py` → `check_ac_index.py` |
| `tests/*.py`, `apps/backend/tests/*.py`, frontend `*.test.*` / `*.spec.*` | `check_ac_index.py` (AC proof traceability) |
| `common/meta/data/MANIFEST.yaml` | `check_ssot_ownership.py`, `check_manifest.py` |
| `docs/*`, `mkdocs.yml`, `vision.md`, `README.md` | `lint_doc_consistency.py` |
| `*.md`, `common/meta/data/*.yaml`, `tests/*.py`, `common/*`, `tools/*.py` | `check_taxonomy_drift.py` (retired taxonomy vocabulary gate, AC-meta.vocab.1) |
| `apps/backend/*schema*.py` | `validate_schemas.py` |
| `apps/backend/migrations/*` | `check_migration_risk.py` |
| `.env*` | `check_env_keys.py` |
| `apps/backend/*.py` | `ruff check` + `ruff format --check` |
| `apps/backend/src/config.py` | `generate_env_reference.py --check` (.env.example / env-reference drift) |
| `apps/backend/src/extraction/extension/statement_*.py` | `test_transaction_boundaries.py` |
| `tools/*`, `common/*` | `pytest tests/tooling/` (tool-wrapper sys.path contract + dispatchers) |
| `apps/frontend/*` | `npm run lint` + `npm run test:coverage` + `npm run build` |

It includes **untracked** files, so new files are checked before they are
committed. The mapping lives in `common/testing/preflight.py` (`CHECKS`); add a new
gate there with a test in `tests/tooling/test_preflight.py`.

## Notes

- Preflight does **not** replace CI — it mirrors a subset, scoped to the diff, for
  fast local feedback.
- It never runs destructive tools (purge/cleanup/deploy). Those stay manual.
- For an EPIC/AC change specifically, see the **ac-workflow** skill for the full
  EPIC→AC→test ritual that preflight's `ac-traceability` gate verifies.
- The `backend-format` gate executes `python -m ruff` with the same Python
  interpreter that runs preflight. Run preflight with the backend venv so the
  local result uses the lockfile-pinned Ruff, matching CI.
