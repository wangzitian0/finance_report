# EPIC -> AC -> Test Workflow

> **SSOT Key**: `tdd-transformation`

## Canonical Hierarchy & AC Home

- **Migrated packages**: `common/<pkg>/contract.py` `roadmap` owns `AC-<pkg>.<group>.<seq>` (`check_package_contract`). Never mirror package ACs into `docs/project/EPIC-*.md`.
- **Horizontal/FE residue**: Explicit `<!-- epic-owned: ... -->` rows stay in `docs/project/EPIC-*.md`.
- **Derived Graph & Gate**: `common/testing/ac_graph.py` (`build_ac_graph()`) joins `generate_ac_registry`, `@ac_proof(...)` decorators (`common/testing/ac_proof.py`), `vision.md`, and `common/testing/data/critical-proof-outcomes.yaml`. No committed snapshots are hand-maintained.

## Proof Semantics & Local Checks

Tests prove behavior via real assertions referencing AC IDs (`expect(true).toBe(true)`, stubs, and pure `pass` fail mandatory AC checks; product E2E root `test_*` functions require `EPIC-xxx` references). Exception infrastructure files are classified in [`docs/project/traceability-exceptions.md`](../../docs/project/traceability-exceptions.md).

Run `python tools/check_manifest.py` and `python tools/check_ssot_ownership.py`; coverage floors live in `common/meta/extension/coverage/policy.py`, `apps/backend/pyproject.toml`, and `apps/frontend/vitest.config.ts`.
