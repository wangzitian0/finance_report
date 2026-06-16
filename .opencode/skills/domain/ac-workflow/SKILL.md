---
name: ac-workflow
description: Follow the mandatory EPIC → AC → Test → Code → Doc order when adding or changing an acceptance criterion (AC). Use this whenever you add/modify an AC, add a test that references an ACx.y.z ID, edit a docs/project/EPIC*.md file, or need the AC registry/traceability gate to pass.
---

# AC workflow — EPIC → AC → Test → Code → Doc

The repo's work order is mandatory and gated in CI. Skipping a step is the most
common reason a PR fails the traceability check.

## The ritual

1. **Anchor to an EPIC.** Find or create the EPIC in `docs/project/EPIC-*.md`.
   Cross-module goals are EPICs; base terms belong in `docs/ssot/`.
2. **Register the AC.** Add a row under the right `### ACx.y:` section of the EPIC
   with: a unique `ACx.y.z` id, a one-line test case, the **exact test function
   name(s)**, the **test file path**, and a priority. Feature ACs live in EPIC
   docs (indexed by `docs/ac_registry.yaml`); infra ACs use `docs/infra_registry.yaml`.
3. **Write the failing test first (🔴).** The test must reference the AC id (in
   the name or a comment) and live at the path you registered.
4. **Write minimal code to pass (🟢).**
5. **Sync SSOT docs** for any base term/contract you touched.

## Always regenerate + verify before pushing

After editing any EPIC/AC, the registry is generated from the EPIC text — it will
drift if you don't regenerate:

```bash
apps/backend/.venv/bin/python tools/generate_ac_registry.py     # sync the index
apps/backend/.venv/bin/python tools/check_ac_index.py           # gate: every mandatory AC has a real CI test
```

The **preflight** skill runs both automatically when it sees an EPIC/registry
change in your diff — prefer `apps/backend/.venv/bin/python tools/preflight.py`
(an interpreter with the project deps) so you can't forget.

## Gotchas (learned the hard way)

- The test function name in the EPIC table must **exactly** match the real test —
  the gate parses both sides.
- Picking an AC number already used by an open PR causes a collision; check open
  PRs for the next free `ACx.y` before claiming one.
- `docs/ac_registry.yaml` is generated — never hand-edit it; edit the EPIC and
  regenerate. The only hand-authored entries live in `docs/ac_registry_overrides.yaml`.
- A new AC with no executing test fails the gate as "missing" — write the test,
  don't just register the row.
