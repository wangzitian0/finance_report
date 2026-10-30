<!-- WS_STATIC_START adapter=rules-v2 inputs=6d18549a5a47ca83e560ce421e2985d6341405c0a5d0985aeef937321b21a772 -->
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
- **Bounded file reads:** Pass `StartLine` and `EndLine` (`<= 800` lines per call) when reading existing files with `read_file` or `view_file`.

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
> **Language**: Write all code, PRs, commits, issues, and repository docs in **English**. Reply to the user in the language of their question.

---

## 🚨 Security & Red Lines (CRITICAL)

Full rules: **[docs/agents/red-lines.md](docs/agents/red-lines.md)**

- **NEVER** use `float` for monetary amounts — use `Decimal`
- **NEVER** commit `.env`, `*.pem`, or credential files
- **NEVER** skip entry balance validation
- **NEVER** use raw `fetch()` in frontend — use `lib/api.ts`
- **NEVER** create `sa.Enum` without explicit `name="..."` parameter

---

## 🧱 Document Hierarchy & Boundaries

Four document roles have zero overlapping ownership:

| Document | Question | Role & Responsibility |
|---|---|---|
| **vision.md** | *Why* | Product vision, architectural north star, and design culture. |
| **Package README / contract.py** | *In what shared language* | Base entities, vocabulary, and data contracts (`common/<pkg>/`). Cross-cutting registry: [common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml). |
| **docs/project/** | *What tracking* | Horizontal EPIC milestone tracking (packages own their ACs in `contract.py`). |
| **README** (root, `apps/*`) | *What per module* | Module goals, setup commands, and build guides. |

No document may usurp another's role: vision does not dictate module internals; EPICs do not redefine package data types.

---

## 🧭 Navigation Map

| Goal | Go to |
|------|-------|
| Project vision & decisions | [vision.md](vision.md) |
| Tech stack, quick start | [README.md](README.md) |
| Concept ownership registry | [common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml) |
| Project tracking & EPICs | [docs/project/README.md](docs/project/README.md) |
| Agent skills | [.agents/skills/](.agents/skills/) |
| Copilot settings | [.github/copilot-instructions.md](.github/copilot-instructions.md) |
| Moon commands / dev setup | [common/meta/development.md](common/meta/development.md) |
| Six environments & isolation | [common/runtime/environments.md](common/runtime/environments.md) |
| CI jobs & test strategy | [common/runtime/ci-cd.md](common/runtime/ci-cd.md) |
| Deployment / Vault / staging | [common/runtime/deployment.md](common/runtime/deployment.md) |
| Data model | [common/meta/schema.md](common/meta/schema.md) |
| Current work | [docs/project/](docs/project/) |

---

## 📐 SSOT-First Principle

Bounded-context concepts live in `common/<pkg>/readme.md` and `contract.py`. Cross-cutting concepts, gate inputs, and generated artifacts live in the governing package's `data/` directory (`common/meta/data/`, `common/testing/data/`, or `common/runtime/`). `docs/ssot/` is retired (#1823). Ownership registry: **[common/meta/data/MANIFEST.yaml](common/meta/data/MANIFEST.yaml)**.

1. **No SSOT, no work**: Define shared terms in the owning package (`readme.md`/`contract.py` or `common/meta/data/`) before writing code.
2. **No hidden drift**: Sync code and its owning document in the same change.
3. **Single owner**: Each concept has one owner file in MANIFEST.

---

## 🔄 Mandatory Work Order

**EPIC → AC → Test → Code → Doc**

> **Planning tasks** (reviews, issue triage, prioritization) run **Vision → Guarantees → Gaps → Actions** with a counterfactual pass before opening an issue ([docs/agents/orchestration.md](docs/agents/orchestration.md)).
> **Bug fixes** identify the root cause, explain why existing gates missed it, and add the missing test in the same PR.

0. Frame a **MECE** breakdown: mutually exclusive slices, collectively exhaustive coverage, explicit dependencies, and out-of-scope items.
1. Anchor to an EPIC in `docs/project/`.
2. Define ACs in the owning package's `contract.py` `roadmap` as `AC-<pkg>.<group>.<seq>` (never mirrored into EPIC tables). `docs/project/EPIC-*.md` keeps only existing residue-marked rows (`<!-- epic-owned: fe-only|fe-half|horizontal|pending-package -->`), ratcheted by `tests/tooling/test_epic_residue_ratchet.py`.
3. Write **failing** tests referencing AC IDs (🔴 red).
4. Write minimal code to pass tests (🟢 green).
5. Update the owning package's contract and readme.

Details: [docs/agents/orchestration.md](docs/agents/orchestration.md) · [common/testing/tdd.md](common/testing/tdd.md)

---

## 🛡️ Pre-Push Gate Parity

- **Before every push**, run `apps/backend/.venv/bin/python tools/preflight.py --tier=static`. Do not push on non-zero exit. Check list SSOT: `tools/preflight.py --list` (#1435).
- **Escape hatch**: If preflight itself is broken, declare `preflight skipped: <reason>` in the PR body.
- **Cloud/sandbox agents**: Run `apps/backend/.venv/bin/python tools/preflight.py --tier=full` before pushing; if dependencies cannot install, declare it via the escape hatch.
- **Coverage**: Run pytest with `--cov` scoped to changed files during TDD; leave full-suite coverage to CI.

---

## 🌿 Branch & PR Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- ❌ No direct commits to `main`. Parallel PR branches must satisfy [branch-policy.md](docs/contributing/branch-policy.md) rule 3.
- Agents merge any PR that satisfies [branch-policy.md](docs/contributing/branch-policy.md) §4.
- A merge that reaches **production** is a production change (Root section `Production reservation`). A protected-file change merges once the protected-file checklist in [branch-policy.md](docs/contributing/branch-policy.md) §4 passes. A merge that only triggers a preview/staging redeploy is the agent's call — see [branch-policy.md](docs/contributing/branch-policy.md) §4.
- Install hooks with `make install`; run `moon run :lint && moon run :test` before pushing.
- Resolve all Copilot review comments by fixing them or stating the rationale; reply on the thread before resolving it.
- Verify `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN` fresh before reporting ready (sibling merges can flip state to `DIRTY`/`BEHIND`); if blocked, report the blocker and next action ([docs/agents/orchestration.md](docs/agents/orchestration.md)).
- State the exact deployed commit/version when claiming staging or production verification.
- Keep watching open PRs for CI runs, review comments, and merge conflicts until merged ([docs/agents/orchestration.md](docs/agents/orchestration.md)). After merge, resync `main`, rebase remaining branches, and start the next slice.
- Make reversible product decisions and record the rationale in the PR or issue. Only a production change waits for the user. While they wait, start the next independent planned slice.

---

## 🧭 Parallel Windows Coordination

- Add an `_infra` affix to local workspace names for infra tasks (e.g., `finance_report_infra_issue-1234-infra`).
- Check issue assignees and open PRs before starting; claim an issue in one place (assign yourself and post branch/worktree name).
- Derive PR title scope from checkout basename: `scope=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")` → `[${scope}] ...`. Only rewrite PRs matching your local `scope`.
- Keep the `ongoing` label on open PRs only; remove it on merge or close.

## 🤖 Agent Architecture

Guides: **[docs/agents/orchestration.md](docs/agents/orchestration.md)** · **[.claude/README.md](.claude/README.md)** · Skills: **[.agents/skills/](.agents/skills/)**

- The active runtime's main loop is the orchestrator. Use the runtime's own subagent list (Claude Code: `.claude/agents/`; OpenCode: `.opencode/oh-my-openagent.json`).
- Delegate read-only search fan-out to cheap search agents; reserve expensive models for hard reasoning. Bound parallelism by write conflicts (vision.md, Good Taste 6).
- Prove UI behavior with tests and pass the `ux-review` skill on simulator or browser captures.

---

## ✍️ Communication & Writing Standards

- **Plain engineering facts**: State exact files changed, rationale, and verification results (commands, exit codes, latency).
- **Banned jargon**: Never use "orthogonal" (outside math), "ontology planes", "terminal residue", "epistemic layer", "emergence", "empowerment", "touchpoint", or "paradigm shift".
- **Zero concealment**: Report exact failing commands, stack traces, and minimal reproduction steps.
<!-- WS_STATIC_END -->
