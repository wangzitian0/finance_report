# Agent Orchestration

> **SSOT Key**: `agent_orchestration`
> **Audience**: AI agents in any runtime (Claude Code, OpenCode, Codex, Gemini).
> Defines the deliverable contract, the development work order, and delegation.

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

**Cross-cutting contract checks** (each owned by
[red-lines.md](./red-lines.md) §Engineering Integrity — listed here only as the
work-order reminder): sync the `repo/` submodule (`infra2`) when a change adds
env vars; every `sa.Enum` carries an explicit `name=`; `NEXT_PUBLIC_` variables
are baked as `ARG`/`ENV` in `apps/frontend/Dockerfile`.

---

## Delegation

The **main loop of the runtime you are in** is the orchestrator; named
subagents are per-runtime mechanics. The per-runtime agent lists, model
routing, and MCP baseline are owned by [`.claude/README.md`](../../.claude/README.md)
(bridge doc covering all four runtimes); the skill library and its admission
rule ("project-specific facts only") are owned by
[`.opencode/README.md`](../../.opencode/README.md).

Judgment, not config (vision.md, Good Taste 6):

- Delegate read-only fan-out — codebase search, external docs — to the cheap
  search agents, in parallel and in the background.
- Reserve the expensive advisory tier for genuinely hard design/debugging
  questions that justify the cost.
- Parallelism is bounded by **write conflicts**, not compute cost: never two
  writers on one surface.
- UI work: behavior is proven by tests; **visual quality is judged by human
  eyes and simulators** — no agent sign-off substitutes for either.

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
