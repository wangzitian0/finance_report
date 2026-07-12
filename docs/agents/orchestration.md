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
- **All Copilot auto-review (CR) comments resolved** — each fixed, or justified — reply on the thread with what changed (or why not) **before** resolving it, so the resolution has a paper trail independent of the commit history
- **GitHub itself reports `mergeable: MERGEABLE` and `mergeStateStatus: CLEAN`** — a green CI run does not imply this; check both explicitly (see the playbook below) before reporting a PR as ready
- Code/PR/commits in English

**`mergeStateStatus` playbook** — this value can flip at any time a sibling PR
merges to `main`, independent of anything you did to this branch. Re-check it
immediately before reporting a PR ready, not just after your last push:

| `mergeStateStatus` | Meaning | Action |
|---|---|---|
| `CLEAN` | Mergeable, checks green, no conflicts | Ready — report it |
| `DIRTY` | Real merge conflict with `main` | Rebase now, don't wait to be told (see below) |
| `BEHIND` | Base moved, no conflict yet | Rebase or merge `main` in before it becomes `DIRTY` |
| `BLOCKED` | Required checks/reviews not yet satisfied | Normal in-flight state — watch, don't rebase pre-emptively |
| `UNSTABLE` | Non-required checks failing | Usually fine to report ready; note which check and why it's non-required |
| `UNKNOWN` | GitHub hasn't computed it yet | Wait ~10-20s and re-query before concluding anything |

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
7. ✅ **Resolve every Copilot (CR) review comment** — fix or justify each, **reply on the thread** with what changed (or why not), then resolve the thread on GitHub
8. ✅ **Report: "PR ready for your review"** — with PR URL, branch, commit SHA,
   draft status, `mergeable`, `mergeStateStatus`, and required-check summary
9. 🔁 **Keep the PR mergeable while waiting** (agents never merge): watch for
   new CI runs, late CR comments, and conflicts caused by other merges — fix
   them unprompted; report state changes only
10. ▶️ **On merge** (detected, or announced by the user): resync `main`, rebase
    any remaining open branches, and continue the next planned slice — report
    plan progress (done / remaining) instead of asking what to do next

**User Workflow**: Review → Approve / Request changes / Reject → **User merges PR**.

---

## PR Lifecycle Loop (anti-babysitting)

Transcript history (19 sessions, 2026-06→07) shows the expensive failure mode
was never writing code — it was the human babysitting every PR to mergeable:
prompting for CI failures (9 sessions), CR comments (15 sessions), and typing
the merge-resync ritual by hand (16 sessions). The loop in steps 6–10 above is
therefore **part of the deliverable, not aftercare**:

- **Watch, don't push-and-forget.** After every push, watch checks to
  completion (`gh pr checks <n> --watch`, or a background monitor). First
  green is a checkpoint, not the finish line.
- **Late CR comments are the same delivery.** Triage each on merit — fix it,
  or justify and resolve the thread. Never blanket-accept, never ignore.
- **A conflict appearing because another PR merged is yours** — rebase
  immediately, don't wait to be told.
- **A claim of "verified against staging/production" is only true if the
  verification mechanism actually targeted the commit you think it did.**
  Concrete failure mode: dispatching a post-merge gate without an explicit
  `version_ref`/commit pin silently defaults to whatever is *currently
  deployed* — if that deploy predates your merge, you've re-tested the old
  code and produced a false "confirmed" signal. Before reporting a live
  verification result, check what commit/version the mechanism actually ran
  against (a deploy's own health/version endpoint, a workflow run's resolved
  ref) and say so explicitly, rather than assuming a dispatch you triggered
  necessarily exercised your latest change.
- **Goals must never require a user-only action.** An agent goal is satisfied
  by "PR(s) mergeable + reported", never by "PR merged" — a goal phrased on
  merging deadlocks the session against the agents-never-merge rule.
- **Post-merge continuation is default-on.** The user's merge is the signal to
  resync and continue the approved plan. Ask only at a genuine decision point
  or when the plan is exhausted.

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

## Bug-Fix Work Order (root-cause + gate backfill)

Every bug fix (from staging QA, production, or review) must answer three
questions in its PR — transcript history shows the user has had to ask them
manually in 8 sessions:

1. **Root cause, not symptom** — the mechanism that produced the behavior,
   not the surface where it appeared.
2. **Why did no existing gate catch it?** — name the tier (unit / integration /
   tier-1 e2e / staging gate / prod smoke) that *should* have caught it.
3. **Back-fill the missing proof in the same PR** — a failing-first test
   (red → green) at that tier; where a same-PR gate is genuinely impossible,
   an explicit issue for the gap. A fix without a locked proof is Good Taste
   5's vacuous safety net — the same bug returns.

Bug-fix PR bodies carry a short **Root cause / Why gates missed it / Proof
added** block.

---

## Planning Work Order (goal-first, counterfactual-gated)

For planning-type tasks — system reviews, issue design/triage, prioritization,
"what next" — the implementation work order above starts too late. Upstream
mandatory sequence (templates and rituals: `planning` skill):

1. **Vision** — restate the terminal goal + North-Star (vision.md) relevant to
   the ask, *before* surveying what exists.
2. **Guarantees** — derive what must hold for that goal (walk the pipeline;
   state guarantees, not tasks).
3. **Gaps** — map the current state against the guarantees. Never rationalize
   bottom-up from the existing inventory toward a conclusion.
4. **Actions** — minimal set; each action's acceptance = the guarantee it
   delivers **plus a lock mechanism** (ratchet / gate / release-evidence check)
   so it cannot silently regress. Name residuals and operator dependencies
   explicitly.
5. **Counterfactual pass before presenting** — "if every acceptance criterion
   is met, what still fails?" Run it yourself; the user should never have to
   ask.

Planning defaults: propose the **minimum-PR plan** (batch cohesive issues into
one PR; run independent PRs in parallel, bounded by write conflicts); rank
actions by ROI; **create no GitHub issues during exploration** — a structure
must survive one simplification pass and one counterfactual pass in
conversation before anything is filed.

---

## Migration / Refactor Closeout

A migration or refactor is not done when the new path works. Done requires a
**residue sweep** — re-requested by the user in 5+ sessions before this was
encoded:

- Old code, config, tests, and docs are deleted, or each survivor is
  explicitly issue-tracked with a reason.
- Rejected design options are recorded with why-not, for the next reader.
- A drift scan of docs + tests: anything still describing the old world is
  updated or deleted in the same PR.

**Cross-cutting contract checks** (each owned by
[red-lines.md](./red-lines.md) §Engineering Integrity — listed here only as the
work-order reminder): sync the `repo/` submodule (`infra2`) when a change adds
env vars; every `sa.Enum` carries an explicit `name=`
(See: [docs/ssot/schema.md#enum-naming](../ssot/schema.md#enum-naming));
`NEXT_PUBLIC_` variables are baked as `ARG`/`ENV` in
`apps/frontend/Dockerfile`.

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
4. **Probe before claiming inability**: never report "can't access X / no
   credentials" without first attempting the documented path — direnv probe
   (`echo ${#VAR}`), the Dokploy API, a read-only VPS SSH log pull, the SigNoz
   non-browser API recipe (see the `infra-operations` skill). If the path truly
   fails, report the exact failing step — never a blanket "can't log in".
5. **Post-deploy verification is part of deploying**: after any deploy or
   release action, verify service health, the running version, and recent
   error logs before reporting success.

---

## Related

- [red-lines.md](./red-lines.md) — Security and integrity hard stops
- [docs/contributing/branch-policy.md](../contributing/branch-policy.md) — Branch and PR rules
- [docs/ssot/tdd.md](../ssot/tdd.md) — TDD workflow details
