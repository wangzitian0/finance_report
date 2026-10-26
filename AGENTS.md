<!-- WS_STATIC_START adapter=rules-v2 inputs=643b7cf85dce83e3f2040dcae8cad7d2c598d72fbac3f963408a9a73fc3f9a35 -->
<!-- Generated file: do not edit by hand. These rules are maintained in the owner's rule source and re-rendered here. -->

## Engineering discipline

- **Measure the physical system first.** Inspect the system with read-only probes (`time cmd`, process chains, file locks) before proposing architecture. Never combine validation and mutation in one command. Measure, read the result, then decide.
- **Green does not prove truth.** The tested system writes its own unit tests, CI, and issue states. Cross-check critical conclusions against two external sources not written by this repository.
- **Tests must be falsifiable.** Never hide assertions inside `if` branches or accept tautologies. Source-text `indexOf` matches against prose are not integration tests. Avoid duplicate test function names that shadow earlier tests. Make every new test fail under a relevant mutation; fake tests are CRITICAL merge blockers.
- **Falsifiable documentation and assertions:** State test requirements, error messages, and specifications in concrete ASD-STE100 terms without vague qualifiers.
- **One source of truth:** Keep one authoritative definition per core fact. Repeated hardcoding and scattered configuration invite drift.
- **Clean up during migration:** After the new mechanism is live and equivalence is proved, remove its predecessor, obsolete files, and dead code in the same change. Define contracts first and derive CI from them.
- **Deletion can leave guards green and empty:** A guard for an old structure can stop checking anything after deletion. Check each guard and remove it or redirect it to the new structure; green tests alone do not prove safe deletion.
- **Define guard scope from what it must govern, not from today's passing tree.** Let the guard fail on existing violations, then repair them. A guard never seen failing is not yet evidence of protection.
- **Worktree self-sufficiency:** Every worktree must resolve its dependencies, toolchain, skills, and configuration internally. Tools and tests must not navigate upward with `../..` to locate files in parent checkouts.
- **Physical context verification:** Static file existence does not prove host runtime context injection. Junior runs non-interactive probes (`-p` or headless exec) with low-cost models, asserting visible specification text across root and deep subdirectories.
- **Host verification scope:** Official host CLIs are the primary execution environment. Regular testing covers Antigravity 2.0 project workspaces (`.agents/skills/` and project rules); standalone desktop chat apps without directory awareness are excluded.
- **Local and remote test segregation:** Inner-loop verification (Senior, Junior, Intern) runs only focused tests on changed files (`pytest <file>::<test> -x`). Full-suite regression runs on remote CI, or locally at most once before merge.
- **Bounded file reads:** Pass `StartLine` and `EndLine` (`<= 250` lines per call) when reading existing files with `read_file` or `view_file`.

## Delivery and merge

- **ASD-STE100 specification for all artifacts:** Write committed artifacts, rules, code, comments, commits, and docs in ASD-STE100 English. Keep instructions `<= 20` words and descriptions `<= 25` words in active voice without vague qualifiers. Operational skills (`skills/**/SKILL.md`) follow the target repository's language policy.
- **Deliverable format:** Deliver a mergeable PR or a traceable issue, rather than a process-only report. Use issues and PRs as the collaboration bus. Search for an existing similar issue before creating one; update it if it exists.
- **Fail fast left to right:** Put the cheapest and likeliest failure checks first.
- **Review standing authorization:** Resolve a review thread after verifying in source code (not redacted diffs) that it is fixed or obsolete. Never resolve actionable or unverified feedback. Turn false reports into falsifiable invariant tests.
- **Weighted review gates:** Each repository defines its own severity weights and blocking thresholds. Read literal `severity: <level>` tags; do not infer severity from prose.
- **Merge when ready:** Once all merge conditions pass, merge and continue from the latest main rather than piling up divergent branches.
- **Delivery state invariant:** Never declare complete, done, or finished before merge to main and a verified Business Reality Probe (`ws-delivery-status`). State labels are `'Draft'`, `'Local verified'`, `'In review'`, `'Stage 1 Landed'`, and `'VERIFIED_COMPLETE'`.
- **Anti-exclusion and reality invariant:** Exclusion is not resolution. Never exclude failing entities or add exemptions to manufacture green checks. A task is complete only when a physical reality probe confirms non-empty execution.
- **Three-stage deployment prerequisite:** Stage 1 (Merge to main) is a non-bypassable physical prerequisite for Stage 2 and Stage 3. If HEAD is not on main, fail closed and refuse any deployment request.
- **Deploy provenance invariant:** Before dispatching any deploy workflow, physically verify that the target ref or tag contains current branch commits (`git merge-base --is-ancestor HEAD <target>`). Never deploy an older tag as completion evidence for current work.

## Production reservation

The single definition of the production reservation. Other tiers, skills and gates point here.

- **Only a production change returns to the owner.** A production change alters what production runs or stores. Examples: a deploy, promote or apply to production; a production secret write; a manual production data write or deletion. Also a production DNS, route or host change, and a release that cannot be recalled. Code that reaches production with no later owner approval, for example on a schedule, counts too. Each Repo tier names its production paths.
- **Approval:** the owner approves the exact commit SHA or release tag of each production change, and is present when it runs. A "deploy" reply covers only the release that it names. Immediately before a production dispatch, get a live reply from the owner.
- **Self-guard:** an edit that removes, narrows or redefines the production reservation needs the owner's approval of its head SHA. This includes an edit that makes fewer production runs wait for the owner. Examples: the owner-approval check of a deploy path, a production job classification, the settings of a production environment. It also includes an edit that removes or weakens a pin of this section or its dev_env pin test. The same holds for the required check that runs the test.
- **Everything else is the agent's:** in a repository that the owner owns, every merge, staging and canary deploy, and release tag. Also rule text, skills, gate code, data and tests, required-check workflows and release code. Before you merge gate or release code, a read-only reviewer that did not write it checks the head. The review states whether the gate gets stricter, stays equal or gets looser. A looser edit in the self-guard list follows the self-guard.
- **Every other hold is a defect:** a rule, skill, label or gate exit code that holds non-production work for the owner. Do the work, then fix the hold. The dev_env check `ws_owner_scope` fails on it.

## Runtime safety

- **Reason from the worst case.** For environment changes, wrappers, redirection, or interception rules, check for no-TTY deadlock in CI or child processes, concurrent shared-file truncation/races, and network or cold-start failure cascades. Reject a proposal whose lack of backlash cannot be established.
- **Treat three hidden green failures as defects:** WRONG FORMULA (an incorrect formula passes assertions), GREEN-WHILE-EMPTY (filtering removes all output but reports success), and STALE-REPORTED-AS-FRESH (old data is labeled fresh). Implausible output is evidence of a defect.
- **Protect ambient services.** Default unit tests and Junior tasks must not destructively act on host ports, shared background processes, or development databases (`DROP`, `TRUNCATE`, `--clear`, forced restart). Resets require an isolated sandbox/worktree with a dedicated random port, or an explicit `CI=true` or `ALLOW_CLEAR_TEST=1` guard; otherwise skip safely with a warning.
- **Two triggers:** Every background job or batch process needs both scheduled execution and manual replay.
- **Do not steal CD locks:** A trigger is instant but publication is delayed. Do not interrupt a running deployment; the next run must coalesce commits accumulated while it was busy.

# Finance Report — Agent & Contributor Guide

> **Rule source**: This file is generated. Change its dev_env source and pass the rule-text checklist; do not hand-edit it.
> **Merge authority**: AI deliverable = CI-passing PR. An agent merges it when every condition in [docs/contributing/branch-policy.md](docs/contributing/branch-policy.md) §4 holds. That covers gate code, workflows and release code once the review that the Root section `Production reservation` requires is on the PR.
> **Production here**: a dispatch of `release.yml` is the production release.
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

## 🧱 Document Hierarchy & Boundaries

The project divides documentation into four distinct roles with zero overlapping ownership:

| Document | Question it answers | Role & Responsibility |
|---|---|---|
| **vision.md** | *Why* | Product vision, architectural north star, and design culture. |
| **Package README / contract.py** | *In what shared language* | Base entities, vocabulary, and data contracts (`common/<pkg>/`). Cross-cutting registry is [common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml). |
| **docs/project/** | *What tracking* | Horizontal EPIC milestone tracking (packages own their own ACs in contract.py). |
| **README** (root, `apps/*`) | *What per module* | Module goals, setup commands, and build guides. |

No document may usurp another document's role: vision does not dictate internal module implementation; EPICs do not redefine base data types owned by packages.

---

## 🧭 Navigation Map

| Goal | Go to |
|------|-------|
| Project vision & decisions | [vision.md](vision.md) |
| Tech stack, quick start | [README.md](README.md) |
| Concept ownership registry (which package owns what) | [common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml) |
| Project tracking & EPICs (never duplicate phase status in this file) | [docs/project/README.md](docs/project/README.md) |
| Agent skills | [.agents/skills/](.agents/skills/) |
| Copilot-specific settings | [.github/copilot-instructions.md](.github/copilot-instructions.md) |

**Routing Rules**:
- Product goal, direction & culture → [vision.md](vision.md)
- Moon commands / environment setup → [common/meta/development.md](common/meta/development.md)
- Six environments (naming, isolation) → [common/runtime/environments.md](common/runtime/environments.md)
- CI job structure / test strategy → [common/runtime/ci-cd.md](common/runtime/ci-cd.md)
- Deployment / Vault / staging → [common/runtime/deployment.md](common/runtime/deployment.md)
- Data model → [common/meta/schema.md](common/meta/schema.md)
- Current work → [docs/project/](docs/project/)

---

## 📐 SSOT-First Principle

Shared base elements and contracts are **authoritative where the package model puts them**: a concept that a bounded-context package governs lives in that package's `common/<pkg>/readme.md` / `contract.py`. A cross-cutting concept (it spans every package), a live gate-data input, or a generated artifact lives in the `data/` dir of one package. That is the package whose governance the data serves: `meta` (`common/meta/data/`), `testing` (`common/testing/data/`), or `runtime` (`common/runtime/`). `docs/ssot/` is retired (#1823). Neither owns goals (vision / EPICs) or module design (READMEs); each owns the *terms* those speak in.  
The ownership registry (which concept lives where) is:
**[common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml)**

1. **No SSOT, no work**: Define the shared terms — in the owning package's
   readme/contract, or `common/meta/data/` if genuinely cross-cutting —
   before writing code.
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
   mirrored back into an EPIC table. `docs/project/EPIC-*.md` is terminal,
   shrink-only residue: only its existing residue-marked rows
   (`<!-- epic-owned: fe-only|fe-half|horizontal|pending-package -->`,
   genuinely horizontal/fe-exception content with no package owner) stay
   EPIC-defined, and adding a new one requires a same-PR baseline edit
   (`tests/tooling/test_epic_residue_ratchet.py`) — new work always starts in
   a package;
   `docs/ac_registry.yaml` / `docs/infra_registry.yaml` are generated index
   stubs (`tools/generate_ac_registry.py`), never hand-edited
3. Write **failing** tests referencing AC IDs (🔴 red)
4. Write minimal code to pass tests (🟢 green)
5. Update the owning package's contract/readme

Details: [docs/agents/orchestration.md](docs/agents/orchestration.md) · [common/testing/tdd.md](common/testing/tdd.md)

---

## 🛡️ Pre-Push Gate Parity

- **Iron rule** — before *any* push, run
  `apps/backend/.venv/bin/python tools/preflight.py --tier=static`
  (seconds-level, diff-aware). Non-zero exit = do **not** push.
- A preflight red is a deterministic preview of a CI red. The check list is
  deliberately not enumerated here — the single source of truth is
  `tools/preflight.py --list` (no fact duplication, #1435 discipline).
- **Escape hatch**: if preflight itself is broken, pushing is allowed, but
  the PR body MUST declare `preflight skipped: <reason>` — never skip silently.
- **Cloud/sandbox agents** (Copilot etc.): additionally run FULL preflight
  (`--tier=full`, includes the tooling suite, ~3 min) before pushing — sandbox
  CPU does not contend with the operator's machine, and a CI retry loop costs
  far more. If the sandbox cannot install deps, declare it in the PR body per
  the escape-hatch rule.
- **Coverage**: during TDD, run your tests with `--cov` scoped to the files
  you changed to confirm your new lines are covered; do **not** run
  full-component coverage locally (~4 min — that is CI's job).

---

## 🌿 Branch & PR Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- ❌ No direct commits to `main`
- Parallel PR branches are allowed when [branch-policy.md](docs/contributing/branch-policy.md) rule 3 holds
- Agents may merge a PR that meets every condition in [branch-policy.md](docs/contributing/branch-policy.md) §4
- A merge that reaches **production** is a production change (Root section `Production reservation`). A protected-file change merges once the protected-file checklist in [branch-policy.md](docs/contributing/branch-policy.md) §4 passes. A merge that only triggers a preview/staging redeploy is the agent's call — see [branch-policy.md](docs/contributing/branch-policy.md) §4 for exactly which workflows reach which environment.
- Install pre-commit hooks: `make install`
- Run `moon run :lint && moon run :test` before pushing
- A mergeable PR must resolve all Copilot auto-review comments (either by fixing them or providing a justification for not doing so). Reply on the thread with what changed *before* resolving it, then resolve the thread on GitHub.
- If GitHub does not report `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`, the task is not a mergeable-PR delivery; report the blocker, the failing/pending check or review thread, and the next action instead of calling the work complete. `mergeStateStatus` can flip from `CLEAN` to `DIRTY`/`BEHIND` the instant a sibling PR merges to `main` — re-check it fresh before every "ready" report, never trust an earlier snapshot; see the playbook in [docs/agents/orchestration.md](docs/agents/orchestration.md).
- A "verified against staging/production" claim is only true if the verification mechanism actually targeted the commit you think it did (e.g. a post-merge gate dispatched without an explicit version/commit pin defaults to whatever is *currently deployed*, which may predate your merge) — confirm and state the actual commit/version before reporting a live result.
- Delivery does not end at first green: keep watching the open PR (new CI runs, late CR comments, conflicts from other merges) and fix regressions unprompted, until the PR is merged (by you once §4 holds; when §4 fails, fix the cause) — see the PR Lifecycle Loop in [docs/agents/orchestration.md](docs/agents/orchestration.md).
- The merge (announced or detected) is itself the continue signal: resync `main`, rebase remaining branches, and proceed to the next planned slice without waiting for a fresh instruction.
- A product judgment is not a reason to stop: decide, record why in the PR or issue, and keep the change reversible. Only a production change waits for the user. While they wait, start the next independent planned slice.

---

## 🧭 Parallel Windows Coordination

- Add an `_infra` suffix or prefix for local workspace identifiers when working on infra tasks (for example: `finance_report_infra_issue-1234-infra`, `issue-1234-infra`).
- Before starting, check issue assignee status + open PR list so the same issue is never claimed by two people.
- Claim an issue in one place only: assign yourself, add a start comment with branch/worktree name.
- If naming conventions conflict with branch policy, prioritize branch/PR naming and adjust only workspace naming to keep uniqueness.
- PR title must include workspace scope derived from the checkout directory basename only:  
  `scope=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")`; title format `[${scope}] ...`.
  - This guarantees scope is unambiguous across local `finance_report*` checkouts.
- Scope rule is local-only and deterministic: only rewrite/validate PRs when title prefix matches current `scope`, never rewrite PRs from another scope.
- `ongoing` is for currently open PRs only; remove it when PR is merged/closed.

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
- UI work: behavior is proven by tests; **visual quality passes the `ux-review`
  skill** on simulator or browser captures of the changed screens.

Skills: [.agents/skills/](.agents/skills/) (see [.claude/README.md](.claude/README.md))

---

## ✍️ Communication & Writing Standards

- **State plain engineering facts**: Commits, PR descriptions, and chat summaries must state exact files changed, rationale, and physical verification results (tests executed, exit codes, latency).
- **Banned Pseudo-Academic Jargon**: Do NOT use terms like "orthogonal" (outside mathematics), "ontology planes", "terminal residue", "epistemic layer", "emergence", "empowerment", "touchpoint", or "paradigm shift".
- **Zero concealment**: If blocked or encountering an error, report the exact failing command, stack trace, and minimal reproduction steps. Never mask uncompleted work behind abstract prose.
<!-- WS_STATIC_END -->
