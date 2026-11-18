---
name: ac-workflow
description: Follow the MECE -> User Case -> Test -> Code -> Doc order in finance_report, anchoring user cases in common/meta/flows/user_cases_ssot.json and package docs in common/<pkg>/readme.md.
---

# Package workflow — user cases and package specs

The mandatory order is **MECE -> User Case -> Test -> Code -> Doc**. Slice work into non-overlapping, collectively exhaustive pieces before writing code.

See `docs/agents/orchestration.md` (work order) and `common/meta/migration-standard.md` (package architecture; package list in `common/meta/base/layering.py::PACKAGE_LAYER`).

## Step 0 — route specifications

- **End-to-end business user cases**: update `common/meta/flows/user_cases_ssot.json`. Never duplicate test tables into `docs/project/EPIC-*.md`.
- **Package contracts and specs**: update `common/<pkg>/readme.md` (and `common/<pkg>/contract/` or `common/<pkg>/conformance/` when used).
- **EPIC anchors**: reference an EPIC in `docs/project/` only as a horizontal goal anchor.

## Steps 1–4

1. **Register or update user cases / invariants** in `common/meta/flows/user_cases_ssot.json` when adding or changing an end-to-end behavior.
2. **Write the failing test first (🔴)** with synthetic or anonymized fixtures (`docs/agents/red-lines.md`).
3. **Write minimal code to pass (🟢).**
4. **Sync docs**: update `common/<pkg>/readme.md` and `common/meta/flows/user_cases_ssot.json`.

## Verification

- Focused TDD uses single-process, coverage-free pytest per Root rule.
- `git push` runs `tools/preflight.py --tier=static` via `pre-commit` (cached per worktree tree/HEAD). Run `apps/backend/.venv/bin/python tools/preflight.py --tier=full` only in sandboxes without pre-push hooks or before final merge.
