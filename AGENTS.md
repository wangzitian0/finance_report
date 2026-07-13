# Finance Report — Agent & Contributor Guide

> **Prohibition**: AI may NOT modify this file without explicit authorization.
> **Prohibition**: AI deliverable = CI-passing PR. User reviews and decides whether to merge.
> **Checklist**: Before completing a task, verify every item in [docs/agents/orchestration.md](docs/agents/orchestration.md).
> **Language**: All code, PRs, commits, issues, and repo docs must be in **English**.
> Conversation with the user follows the **user's language** — answer in the language the question was asked in.

---

## 🚨 Security & Red Lines (CRITICAL)

Full rules: **[docs/agents/red-lines.md](docs/agents/red-lines.md)**

Quick reference:
- **NEVER** use `float` for monetary amounts — use `Decimal`
- **NEVER** commit `.env`, `*.pem`, or credential files
- **NEVER** skip entry balance validation
- **NEVER** use raw `fetch()` in frontend — use `lib/api.ts`
- **NEVER** create `sa.Enum` without explicit `name="..."` parameter

---

## 🧱 Four Orthogonal Concerns

These four are **orthogonal axes, not a hierarchy** — each answers a different
question, so they never compete for ownership:

| Concern | Question it answers | Axis |
|---------|--------------------|------|
| **vision.md** | *Why* — the overall product goal and culture | north star |
| **SSOT** | *In what shared language* — the canonical base elements, vocabulary, and contracts that everything else reuses; a package-owned concept lives in its `common/<pkg>/readme.md`, a cross-cutting/gate-data/generated one lives in `docs/ssot/` — the registry is [docs/ssot/MANIFEST.yaml](docs/ssot/MANIFEST.yaml) | common dictionary |
| **EPIC** (`docs/project/`) | *What, horizontally* — a cross-module goal, verified via `EPIC → AC → test` | feature slice |
| **README** (root, `apps/*`) | *What, per module* — one module's goal and how it is built | module slice |

Because they slice the project on different axes, the **same fact appearing in
more than one is not drift** — each states it in its own register: vision as
direction, SSOT as a defined term, EPIC as a horizontal goal, README as a module
goal. Drift is only when a doc adopts another axis's *job* (e.g. vision dictating
implementation, or an EPIC redefining a base element that SSOT already owns).

---

## 🧭 Navigation Map

| Goal | Go to |
|------|-------|
| Project vision & decisions | [vision.md](vision.md) |
| Tech stack, quick start | [README.md](README.md) |
| **All SSOT docs** | [docs/ssot/README.md](docs/ssot/README.md) |
| Project tracking & EPICs | [docs/project/README.md](docs/project/README.md) |
| Agent skills | [.opencode/skills/](.opencode/skills/) |
| Copilot-specific settings | [.github/copilot-instructions.md](.github/copilot-instructions.md) |

**Routing Rules**:
- Product goal, direction & culture → [vision.md](vision.md)
- Moon commands / environment setup → [docs/ssot/development.md](docs/ssot/development.md)
- Six environments (naming, isolation) → [docs/ssot/environments.md](docs/ssot/environments.md)
- CI job structure / test strategy → [docs/ssot/ci-cd.md](docs/ssot/ci-cd.md)
- Deployment / Vault / staging → [docs/ssot/deployment.md](docs/ssot/deployment.md)
- Data model → [docs/ssot/schema.md](docs/ssot/schema.md)
- Current work → [docs/project/](docs/project/)

---

## 📐 SSOT-First Principle

The shared base elements and contracts — the common language the rest of the
repo reuses — are **authoritative wherever the package-model migration puts
them**, not always `docs/ssot/`: a concept a bounded-context package governs
lives in that package's `common/<pkg>/readme.md`; a concept that is genuinely
cross-cutting (spans every package), a live gate-data input, or a generated
artifact lives in `docs/ssot/`. Neither owns goals (vision / EPICs) or module
design (READMEs); each owns the *terms* those speak in — see
[docs/ssot/README.md](docs/ssot/README.md) for the current file-by-file map.  
The ownership registry (which concept lives where) is:
**[docs/ssot/MANIFEST.yaml](docs/ssot/MANIFEST.yaml)**

1. **No SSOT, no work**: Define the shared terms — in the owning package
   readme, or `docs/ssot/` if genuinely cross-cutting — before writing code.
2. **No hidden drift**: When code differs from its owning doc, sync immediately.
3. **Single owner**: Each concept has exactly one owner file; see MANIFEST.

---

## 🔄 Mandatory Work Order

**EPIC → AC → Test → Code → Doc**

> **Planning-type tasks** (system reviews, issue design/triage, prioritization,
> "what should we do next") start further upstream: **Vision → Guarantees →
> Gaps → Actions**, with a counterfactual pass *before* any GitHub issue is
> created. Use the `planning` skill; work order details in
> [docs/agents/orchestration.md](docs/agents/orchestration.md).
> **Bug fixes** follow the bug-fix work order there too: root cause → why no
> existing gate caught it → back-fill the missing proof in the same PR.

0. Frame the work with a **MECE** breakdown: mutually exclusive task slices, collectively exhaustive coverage of the stated goal, explicit dependencies, and explicit out-of-scope items.
1. Anchor to an EPIC in `docs/project/` (the horizontal goal)
2. Define ACs where they live: a **migrated package** owns its ACs as
   `AC-<pkg>.<group>.<seq>` in that package's `contract.py` `roadmap` — never
   mirrored back into an EPIC table. Only legacy, not-yet-migrated modules
   still add ACs as explicitly residue-marked rows in a
   `docs/project/EPIC-*.md` table (`<!-- epic-owned: ... -->`);
   `docs/ac_registry.yaml` / `docs/infra_registry.yaml` are generated index
   stubs (`tools/generate_ac_registry.py`), never hand-edited
3. Write **failing** tests referencing AC IDs (🔴 red)
4. Write minimal code to pass tests (🟢 green)
5. Update the owning package contract/readme (or SSOT docs for legacy modules)

Details: [docs/agents/orchestration.md](docs/agents/orchestration.md) · [docs/ssot/tdd.md](docs/ssot/tdd.md)

---

## 🛡️ Pre-Push Gate Parity

- ✅ **Iron rule** — before *any* push, run
  `apps/backend/.venv/bin/python tools/preflight.py --tier=static`
  (seconds-level, diff-aware). Non-zero exit = do **not** push.
- A preflight red is a deterministic preview of a CI red. The check list is
  deliberately not enumerated here — the single source of truth is
  `tools/preflight.py --list` (no fact duplication, #1435 discipline).
- ✅ **Escape hatch**: if preflight itself is broken, pushing is allowed, but
  the PR body MUST declare `preflight skipped: <reason>` — never skip silently.
- ✅ **Cloud/sandbox agents** (Copilot etc.): additionally run FULL preflight
  (`--tier=full`, includes the tooling suite, ~3 min) before pushing — sandbox
  CPU does not contend with the operator's machine, and a CI retry loop costs
  far more. If the sandbox cannot install deps, declare it in the PR body per
  the escape-hatch rule.
- ✅ **Coverage**: during TDD, run your tests with `--cov` scoped to the files
  you changed to confirm your new lines are covered; do **not** run
  full-component coverage locally (~4 min — that is CI's job).

---

## 🌿 Branch & PR Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- ❌ No direct commits to `main`
- ✅ User-approved parallel PR branches are allowed
- ❌ Agents never merge PRs
- ✅ Install pre-commit hooks: `make install`
- ✅ Run `moon run :lint && moon run :test` before pushing
- ✅ A mergeable PR must resolve all Copilot auto-review comments (either by fixing them or providing a justification for not doing so). Reply on the thread with what changed *before* resolving it, then resolve the thread on GitHub.
- ✅ For implementation work, the final deliverable is not complete until a ready PR is pushed and the final report includes PR URL, branch, commit SHA, draft status, `mergeable`, `mergeStateStatus`, and required-check summary.
- ✅ If GitHub does not report `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`, the task is not a mergeable-PR delivery; report the blocker, the failing/pending check or review thread, and the next action instead of calling the work complete. `mergeStateStatus` can flip from `CLEAN` to `DIRTY`/`BEHIND` the instant a sibling PR merges to `main` — re-check it fresh before every "ready" report, never trust an earlier snapshot; see the playbook in [docs/agents/orchestration.md](docs/agents/orchestration.md).
- ✅ A "verified against staging/production" claim is only true if the verification mechanism actually targeted the commit you think it did (e.g. a post-merge gate dispatched without an explicit version/commit pin defaults to whatever is *currently deployed*, which may predate your merge) — confirm and state the actual commit/version before reporting a live result.
- ✅ Delivery does not end at first green: keep watching the open PR (new CI runs, late CR comments, conflicts from other merges) and fix regressions unprompted, until the user merges — see the PR Lifecycle Loop in [docs/agents/orchestration.md](docs/agents/orchestration.md).
- ✅ The user's merge (announced or detected) is itself the continue signal: resync `main`, rebase remaining branches, and proceed to the next planned slice without waiting for a fresh instruction.
- ✅ Blocked on a user-only action (merging, product judgment)? Don't stall — state the blocker and start the next independent planned slice.

---

## 🧭 Parallel Windows Coordination

- ✅ Add an `_infra` suffix or prefix for local workspace identifiers when working on infra tasks (for example: `finance_report_infra_issue-1234-infra`, `issue-1234-infra`).
- ✅ Before starting, check issue assignee status + open PR list so the same issue is never claimed by two people.
- ✅ Claim an issue in one place only: assign yourself, add a start comment with branch/worktree name.
- ✅ `_infra` labels are local coordination tags only; they do not block GitHub assignment by themselves.
- ✅ If naming conventions conflict with branch policy, prioritize branch/PR naming and adjust only workspace naming to keep uniqueness.
- ✅ PR title must include workspace scope derived from the checkout directory basename only:  
  `scope=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")`; title format `[${scope}] ...`.
  - Example 1: `finance_report_infra` -> `[finance_report_infra] ...`
  - Example 2: `finance_report_ui` -> `[finance_report_ui] ...`
  - This guarantees scope is unambiguous across `~/zitian/finance_report*` workspaces.
- ✅ Scope rule is local-only and deterministic: only rewrite/validate PRs when title prefix matches current `scope`, never rewrite PRs from another scope.
- ✅ `ongoing` is for currently open PRs only; remove it when PR is merged/closed.

## 🤖 Agent Architecture

Full guide: **[docs/agents/orchestration.md](docs/agents/orchestration.md)** ·
Per-runtime agents & MCP baseline: **[.claude/README.md](.claude/README.md)**

- The **main loop of the runtime you are in** is the orchestrator. Named
  subagents are per-runtime mechanics (Claude Code: `.claude/agents/`;
  OpenCode: `.opencode/oh-my-openagent.json`) — use the runtime's own list,
  and never hard-require an agent another runtime does not have.
- Delegate read-only fan-out (codebase search, external docs) to the cheap
  search agents; reserve the expensive tier for genuinely hard advisory
  reasoning. Parallelism is bounded by write conflicts, not by compute cost
  (vision.md, Good Taste 6).
- UI work: behavior is proven by tests; **visual quality is judged by human
  eyes and simulators** — no agent sign-off substitutes for either.

Skills: [.opencode/skills/](.opencode/skills/) (canonical library; other
runtimes symlink into it — see [.claude/README.md](.claude/README.md))

---

## 📅 Project Phase

Use [docs/project/README.md](docs/project/README.md) for current project
tracking. Do not duplicate phase status in this quick-reference file.

---

## 📁 Documentation Map

| Category | Path | Purpose |
|----------|------|---------|
| **Agent governance** | `docs/agents/` | Red lines, orchestration |
| **Contributor guide** | `docs/contributing/` | Branch policy, pre-commit |
| **SSOT** | `docs/ssot/` | Cross-cutting infra docs, live gate-data inputs, generated artifacts, and the concept-ownership registry (`MANIFEST.yaml`) — package-owned concepts live in `common/<pkg>/readme.md` instead |
| **Project EPICs** | `docs/project/` | Horizontal (cross-module) goals & tracking |
| **Module READMEs** | `apps/*/README.md` | Per-module goal & design guide |
