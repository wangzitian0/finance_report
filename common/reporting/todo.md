# `reporting` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md) and is tracked by EPIC-026 Lane B (#1387).

## Done

- [x] Scaffold the bounded context: `contract.py` (draft) + `readme.md` + `todo.md`,
      authority tier pinned `CODE-ONLY` (#1387 Lane B).

## Next (the migration recipe, one PR per step where sensible)

- [ ] **Define the `ReportLineId` registry** — the enumerated, framework-tagged
      line set (US ∪ HK union) replacing free-form `line_mappings` in
      `framework_policy.py`. This is the design input #1353 is blocked on; needs
      sign-off on the line taxonomy (which lines, framework tagging, ordering).
- [ ] Migrate `apps/backend/src/services/reporting` → `apps/backend/src/reporting`
      with role-converged `types/ops/store/api`; set `implementations["be"]` and
      make `__init__.__all__` equal `contract.interface`.
- [ ] Add the **report-lines-reconcile** invariant with an `exact` aggregation
      test (fixed L1 fixture → byte-exact statement) — the proof #1397 marks
      pending and #1353 owns.
- [ ] Add the **framework-1:1** invariant test (US vs HK line selection + order).
- [ ] Move EPIC-005 reporting ACs into `roadmap` as package-scoped
      `AC-reporting.<group>.<seq>`, repointing references in the same change.
- [ ] Flip `status` → `active` once the implementation conforms and the tier's
      `exact` proofs are anchored.
