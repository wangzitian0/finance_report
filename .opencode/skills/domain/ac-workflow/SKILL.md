---
name: ac-workflow
description: Route a new or changed acceptance criterion (AC) to its correct home — a migrated package's contract.py roadmap first, EPIC tables only for legacy surfaces — then follow the mandatory MECE → AC → Test → Code → Doc order. Use this whenever you add/modify an AC, add a test that references an AC id (AC-<pkg>.* or ACx.y.z), edit a package contract.py roadmap or a docs/project/EPIC*.md file, or need the AC registry/traceability/dual gate to pass.
---

# AC workflow — package roadmap first, EPIC table only for legacy

The culture is `EPIC → AC → Test → Code → Doc` (every behavior anchors to a
goal and is proven by a test); the mandatory sequence is
**MECE → AC → Test → Code → Doc** — slice the work into non-overlapping,
collectively exhaustive pieces *before* touching ACs. The **mechanism** for
*where an AC lives* is the package contract, not an EPIC table — see
`docs/agents/orchestration.md` (work order) and
`common/meta/migration-standard.md` (the target architecture).

## Step 0 — route the AC (this decides everything else)

Does the owning package have a `common/<pkg>/contract.py`? (Check
`ls common/*/contract.py`; membership is `common/meta/base/layering.py::PACKAGE_LAYER`.
In practice a new AC almost always belongs to a package now.)

- **Migrated package** → the AC lives in that package's `contract.py`
  `roadmap` as an `ACRecord` with id `AC-<pkg>.<group>.<seq>` — `<group>` is an
  entity name or a numeric group (e.g. `AC-ledger.journal-entry.3`,
  `AC-identity.1.2`). **Never** add it to an EPIC table and never mirror it
  back there — `check_epic_package_dual` fails CI when the same id lives in
  both sources.
- **Legacy surface only** (no owning package — a shrinking set) → the old
  flow: a row in the owning `docs/project/EPIC-*.md` table, materialized via
  `docs/ac_registry.yaml` (feature) or `docs/infra_registry.yaml` (infra).
- **Moving an existing EPIC row into a package is atomic**: delete the EPIC
  row and add the roadmap entry in the *same PR* (the dual gate enforces
  exactly this shape).

Either way, still anchor the *work* to an EPIC in `docs/project/` as its
horizontal goal — the anchor is a goal reference, not the AC's home.

## The ritual (after routing)

1. **Write the AC.**
   - Package: append an `ACRecord(id=..., statement=...,
     test="apps/backend/tests/<pkg>/test_x.py::test_name", priority=...,
     status=...)` to the `roadmap` (schema:
     `common/meta/base/package_contract.py`).
   - Legacy: add a row under the right `### ACx.y:` section of the EPIC with a
     unique `ACx.y.z` id, a one-line test case, the **exact test function
     name(s)**, the **test file path**, and a priority.
2. **Write the failing test first (🔴).** The test must reference the AC id
   (in the name or a comment) and live at the path you registered.
3. **Write minimal code to pass (🟢).**
4. **Doc sync.** Migrated package: its `contract.py`/`readme.md`. Legacy: the
   SSOT doc owning any base term you touched.

## Always regenerate + verify before pushing

The registry aggregates **both** sources (package roadmaps + legacy EPIC
tables) — it drifts if you don't regenerate:

```bash
apps/backend/.venv/bin/python tools/generate_ac_registry.py     # sync the index
apps/backend/.venv/bin/python tools/check_ac_index.py           # gate: every mandatory AC has a real CI test
apps/backend/.venv/bin/python tools/check_epic_package_dual.py  # gate: no AC id lives in both sources
```

The **preflight** skill picks the right gates for your diff — prefer
`apps/backend/.venv/bin/python tools/preflight.py` (an interpreter with the
project deps) so you can't forget.

## Gotchas (learned the hard way)

- The `test` field / EPIC-table test name must **exactly** match the real
  test — the gates parse both sides.
- The same AC id in a roadmap AND an EPIC table turns
  `check_epic_package_dual` red; the fix is deleting the EPIC row, not the
  roadmap entry (migration never lowers a standard — #1416 Decision A).
- `docs/ac_registry.yaml` is generated — never hand-edit it; edit the
  roadmap/EPIC and regenerate. The only hand-authored entries live in
  `docs/ac_registry_overrides.yaml`.
- A new AC with no executing test fails the gate as "missing" — write the
  test, don't just register the row.
- Picking an AC number already used by an open PR causes a collision; check
  open PRs for the next free `<group>.<seq>` before claiming one.
