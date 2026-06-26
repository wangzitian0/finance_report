# Agent Orchestration

> **SSOT Key**: `agent_orchestration`
> **Audience**: AI agents (Sisyphus and sub-agents).
> Defines delegation rules, STAR problem-solving framework, and deliverable scope.

---

## Agent Deliverable Contract

**What Agent Delivers**: A **mergeable PR** (NOT merged code).

**Definition of a mergeable PR** — every item must hold:
- On a branch, never committed to `main`
- **CI passing** (all required checks green) — behavior is proven by the tests in CI
  (TDD / root-cause), **not** by manually watching a preview deploy
- **All Copilot auto-review (CR) comments resolved** — each fixed, or justified — and the comment **threads resolved on GitHub**
- Code/PR/commits in English

> Manual preview verification (`report-pr-XX.zitian.party`) is **optional** — useful
> to eyeball a UI change, but not a required deliverable step. The proof of behavior
> lives in the test suite, not in watching the app run.

**Agent Workflow (Complete)**:

1. ✅ Understand requirements
2. ✅ Design solution
3. ✅ Write failing tests (TDD)
4. ✅ Write minimal code to pass
5. ✅ Create PR (branch only — never commit to `main`)
6. ✅ **Monitor CI until it passes** (use `gh run watch`)
   - If CI fails: find the root cause, fix, repeat
7. ✅ **Resolve every Copilot (CR) review comment** — fix or justify each — then resolve the threads on GitHub
8. ✅ **Report: "PR ready for your review"**
9. ⏸️ **STOP. Wait for user decision.** (Agents never merge.)

**User Workflow**: Review → Approve / Request changes / Reject → **User merges PR**.

---

## 🛠️ Problem Solving Framework (STAR)

Use this cascade **before processing any task**:

### 1. Situation (Context Assessment)
- **Anchor Project**: Bind to a project in `docs/project/`
- **Current State**: Describe system status and problem impact
- **Truth Check**: Read relevant `docs/ssot/` topics; identify gap between current and ideal

### 2. Tasks (Multi-Dimensional Breakdown)
- Break down based on Situation
- Assign to layers: **Backend** (`apps/backend/`) / **Frontend** (`apps/frontend/`) / **Infra** (`repo/` submodule)
- Apply **MECE task framing** before implementation:
  - **Mutually exclusive**: each task slice has one owner and does not overlap with another slice's code, AC, or proof responsibility.
  - **Collectively exhaustive**: the task set covers every stated user outcome, acceptance criterion, and vision-critical proof path.
  - **Dependencies explicit**: blockers, prerequisites, parallelizable work, and follow-up work are named before execution.
  - **Out of scope explicit**: adjacent issues, hygiene work, and deferred risks are parked deliberately rather than mixed into the main task.

### 3. Actions (Execution Steps)
- Define specific action sequence for each task
- **Contract Validation**:
  - **Infra Check**: Sync `repo` submodule (`infra2`) when adding env vars
  - **DB Check**: Ensure explicit `name` for Enums and check migration length
  - **Next.js Check**: Add `NEXT_PUBLIC_` variables to `Dockerfile` `ARG`
- **Closed-Loop Changes**: Code change → Update SSOT → Verify → Update README

### 4. Result (Verification)
- **Self-Check**: Compare against project goals in [Project Vision](../target.md)
- **Engineering Audit**:
  - [ ] **MECE Task Frame**: Are task slices non-overlapping, complete for the stated goal, and clear about dependencies and out-of-scope work?
  - [ ] **Submodule Sync**: Did I update `infra2` for config changes?
  - [ ] **Enum Naming**: Are all `sa.Enum` fields explicitly named?
  - [ ] **Next.js Bake**: Are `NEXT_PUBLIC_` variables added to `Dockerfile` `ARG`?
- **Evidence Loop**: Use verification methods from SSOT "The Proof" sections
- **Update Docs**: Update README, Project docs, SSOT as needed

---

## Development Work Order (TDD-First)

**The culture is `EPIC → AC → test`** (vision's north-star discipline: every
behavior is anchored to a goal and proven by a test). The **mechanism** for
*where an AC lives* is the **package contract**, not an EPIC table:

**Mandatory sequence: MECE → AC (package `roadmap`) → Test → Code → Doc**

0. **MECE**: Split the work into non-overlapping slices that collectively
   cover the stated goal; name dependencies and out-of-scope work before
   implementation.
1. **AC home — the package `roadmap`**: For a **migrated** package, define the
   acceptance criterion as `AC-<pkg>.<group>.<seq>` (the `<group>` segment is an
   entity name **or** a numeric group, e.g. `AC-ledger.journal-entry.3` or
   `AC-counter.1.1`) in that package's
   `contract.py` `roadmap`, conforming to `meta`'s schema
   ([`common/meta/migration-standard.md`](../../common/meta/migration-standard.md)).
   `meta`'s data layer aggregates these; **never mirror a package AC back into an
   EPIC table.** Anchor the slice to a project EPIC in `docs/project/` as its
   horizontal goal — but the AC is owned by the package once that package is
   migrated.
   - **Legacy (not-yet-migrated) modules only**: the AC still lives in the
     owning EPIC and materializes through `docs/ac_registry.yaml` (feature) or
     `docs/infra_registry.yaml` (infra), with historical/non-derived metadata in
     `docs/ac_registry_overrides.yaml`. This EPIC-table source is being phased
     out package by package; once a module becomes a package its ACs move into
     the `roadmap`.
2. **Test**: Write failing tests that reference the AC IDs (red phase).
   Regression fixtures and test data MUST be generated/anonymized, never
   derived from real user uploads or real statements — see the financial-data
   red line in [red-lines.md](./red-lines.md).
3. **Code**: Write minimal code to make the tests pass (green phase)
4. **Doc**: Update the package `readme`/contract (or, for legacy modules, SSOT
   docs and README)

**Hard constraints**:
- ❌ **NEVER** write code before the test exists
- ❌ **NEVER** write a test without a registered AC number (a package `roadmap`
  AC for migrated packages; an EPIC/registry AC for legacy modules)
- ❌ **NEVER** ship without updating the owning package's contract/readme (or
  SSOT docs for legacy modules)

Reference: [docs/ssot/tdd.md](../ssot/tdd.md) ·
[package migration standard](../../common/meta/migration-standard.md)

---

## Three-Layer Agent System

**Orchestrator → Agents → Skills**

### Configured Agents

| Agent | Cost | When to Use |
|-------|------|-------------|
| **Sisyphus** | — | Main orchestrator; handles most tasks directly via skills |
| `explore` | FREE | Codebase exploration, parallel grep (use in background) |
| `librarian` | FREE | External docs, OSS examples (use in background) |
| `frontend-ui-ux-engineer` | MEDIUM | **Mandatory** for visual/styling changes |
| `multimodal-looker` | MEDIUM | Image/PDF analysis |
| `oracle` | EXPENSIVE | Architecture decisions, debugging (use sparingly) |

### Sisyphus Delegation Rules

Delegate ONLY for:
1. **Parallel exploration** → `explore` + `librarian` (background, parallel)
2. **Visual changes** → `frontend-ui-ux-engineer` (mandatory for CSS/styling)
3. **Image/PDF analysis** → `multimodal-looker`
4. **Architecture decisions** → `oracle`

### Skill Categories

```
.opencode/skills/
├── domain/              # Project-specific (from SSOT)
│   ├── accounting/      # Double-entry bookkeeping
│   ├── reconciliation/  # Statement matching
│   ├── reporting/       # Financial statements
│   ├── extraction/      # Document parsing
│   ├── schema/          # Database models
│   ├── development/     # Moon commands, CI/CD
│   └── infra-operations/ # Deployment, secrets, debugging
├── professional/        # Reusable expertise
│   ├── backend-development/
│   ├── frontend-react/
│   ├── qa-testing/
│   ├── ui-ux-design/
│   ├── product-management/
│   └── auditor/
└── meta/
    └── skill-writer/
```

---

## Operational Guidelines

1. **Prefer Dokploy API for debugging**: Use `curl` + Dokploy API; SSH only for reading, never modifying.
2. **Shared network isolation**: Use compose service DNS on project-scoped networks for PR previews; do not use fixed container names as hostnames.
3. **Infrastructure Submodule Sync**: Before creating PR, verify `repo/` points to latest `infra2` main:
   ```bash
   cd repo && git fetch origin main && git log --oneline -1 origin/main && git log --oneline -1 HEAD
   ```

---

## Related

- [red-lines.md](./red-lines.md) — Security and integrity hard stops
- [docs/contributing/branch-policy.md](../contributing/branch-policy.md) — Branch and PR rules
- [docs/ssot/tdd.md](../ssot/tdd.md) — TDD workflow details
