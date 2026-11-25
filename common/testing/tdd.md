# Two-Layer Contract & Flow Test Workflow

> **SSOT Key**: `tdd-transformation`

## Canonical Hierarchy

- **Domain invariants**: Verified directly in each package's backend/frontend test suite and enforced structurally by `tools/check_app_boundary.py`, `tools/check_base_purity.py`, and `tools/check_tier_imports.py`. Core financial and security invariants are pinned in [`common/testing/invariant_core.py`](./invariant_core.py) (`pytest -m invariant_core`).
- **Business user cases**: `common/meta/flows/user_cases_ssot.json` owns the 47 end-to-end `UC-01..UC-47` journeys across backend APIs, frontend routes, and test modules.
- **Documentation boundary**: Never mirror per-test acceptance tables into `docs/project/EPIC-*.md`.

## Proof Semantics & Local Checks

Tests prove real invariants or user-case journeys (`expect(true).toBe(true)`, stubs, and pure `pass` violate testing discipline). Exception infrastructure files are classified in [`docs/project/traceability-exceptions.md`](../../docs/project/traceability-exceptions.md). Coverage metrics report to the quality dashboard from `apps/backend/pyproject.toml` and `apps/frontend/vitest.config.ts` without blocking thresholds.
