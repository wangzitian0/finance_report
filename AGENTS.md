<!-- WS_STATIC_START adapter=rules-v2 inputs=b99e424d95b940b4a1eb4e28425033224729f9733f030fcaf21780c5a8e16a5e -->
<!-- Generated file: do not edit by hand. These rules are maintained in the owner's rule source and re-rendered here. -->

## Engineering discipline

- **Measure the physical system first.** Inspect the system with read-only probes (`time cmd`, process chains, file locks) before proposing architecture. Never combine validation and mutation in one command. Measure, read the result, then decide.
- **Green does not prove truth.** The tested system writes its own unit tests, CI, and issue states. Cross-check critical conclusions against two external sources not written by this repository.
- **Tests must be falsifiable.** Never hide assertions inside `if` branches or accept tautologies. Source-text `indexOf` matches against prose are not integration tests. Avoid duplicate test function names that shadow earlier tests. Make every new test fail under a relevant mutation; fake tests are CRITICAL merge blockers.
- **Falsifiable documentation and assertions:** State test requirements, error messages, and specifications in concrete ASD-STE100 terms without vague qualifiers.
- **One source of truth:** Keep one authoritative definition per core fact. Repeated hardcoding and scattered configuration invite drift.
- **Clean up during migration:** After the new mechanism is live and equivalence is proved, remove its predecessor, obsolete files, and dead code in the same change. Define contracts first and derive CI from them.
- **Deletion can leave guards green and empty:** A guard for an old structure can stop checking anything after deletion. Check each guard and remove it or redirect it to the new structure; green tests alone do not prove safe deletion.
- **Fix an owner hold by deletion:** Delete the rule or gate branch that holds non-production work. Do not add logic that reads a command to permit it. Such logic lets unsafe commands through.
- **Define guard scope from what it must govern, not from today's passing tree.** Let the guard fail on existing violations, then repair them. A guard never seen failing is not yet evidence of protection.
- **Worktree self-sufficiency:** Every worktree must resolve its dependencies, toolchain, skills, and configuration internally. Tools and tests must not navigate upward with `../..` to locate files in parent checkouts.
- **Local and remote test segregation:** Before a PR, run only the focused tests of the change in one process (`pytest <file>::<test> -x`). The full suite, parallel runs and coverage run on remote CI only.
- **Bounded file reads:** Pass `StartLine` and `EndLine` (`<= 800` lines per call) when reading existing files with `read_file` or `view_file`.

## Delivery and merge

- **ASD-STE100 specification for all artifacts:** Write committed artifacts, rules, code, comments, commits, and docs in ASD-STE100 English. Keep instructions `<= 20` words and descriptions `<= 25` words in active voice without vague qualifiers. Operational skills (`skills/**/SKILL.md`) follow the target repository's language policy.
- **Deliverable format:** Deliver a mergeable PR or a traceable issue, rather than a process-only report. Use issues and PRs as the collaboration bus. Search for an existing similar issue before creating one; update it if it exists. Write a new issue to the issue form of its type in `.github/ISSUE_TEMPLATE/` of the repository, else of its owner's `.github` repository.
- **Fail fast left to right:** Put the cheapest and likeliest failure checks first.
- **Review standing authorization:** Resolve a review thread after verifying in source code (not redacted diffs) that it is fixed or obsolete. Never resolve actionable or unverified feedback. Turn false reports into falsifiable invariant tests.
- **Weighted review gates:** Each repository defines its own severity weights and blocking thresholds. Read literal `severity: <level>` tags; do not infer severity from prose.
- **Merge when ready:** Once all merge conditions pass, merge and continue from the latest main rather than piling up divergent branches.
- **Conflict-free merge window:** Merge conflict-free PRs (`mergeable=MERGEABLE`) within 24 hours of `main` without rebasing; post-merge CI validates `main`. Rebase on conflicts or after 24 hours.
- **Delivery state invariant:** Never declare complete, done, or finished before merge to main and a verified Business Reality Probe (`ws-delivery-status`). State labels are `'Draft'`, `'Local verified'`, `'In review'`, `'Stage 1 Landed'`, and `'VERIFIED_COMPLETE'`.
- **Anti-exclusion and reality invariant:** Exclusion is not resolution. Never exclude failing entities or add exemptions to manufacture green checks. A task is complete only when a physical reality probe confirms non-empty execution.
- **Three-stage deployment prerequisite:** Stage 1 (merge to main) is a non-bypassable physical prerequisite for Stage 2 (staging) and Stage 3 (production). If HEAD is not on main, fail closed and refuse any deployment request.
- **Deploy provenance invariant:** Before dispatching any deploy workflow, physically verify that the target ref or tag contains current branch commits (`git merge-base --is-ancestor HEAD <target>`). Never deploy an older tag as completion evidence for current work.

## Production reservation

The single definition of the production reservation. Other tiers, skills and gates point here.

- **Only a production change returns to the owner.** A production change alters what production runs or stores (deploy, promote or apply to production; production secret write; manual production data write or deletion; production DNS, route or host change; unrecallable release; or scheduled unapproved production code). Each Repo tier names its production paths. A path can be a merge or a release-checkout pull.
- **Approval:** the owner approves the exact commit SHA or release tag of each production change, and is present when it runs. A "deploy" reply covers only the release that it names. Immediately before a production dispatch, get a live reply from the owner.
- **Self-guard:** an edit that removes, narrows or redefines the production reservation needs the owner's approval of its head SHA. This includes an edit that makes fewer production runs wait for the owner (deploy-path approval check, production job classification, or production environment settings). It also covers removing or weakening a pin of this section, its pin test, or the required check that runs the test.
- **Everything else is the agent's:** in any repository the owner owns, every non-production change (including `dev_env` outside the self-guard), staging and canary deploy, release tag, rule text, skill, gate/release code, and required-check edit. Before merging gate or release code, an independent read-only reviewer inspects the head SHA and states whether the gate gets stricter, equal or looser. A looser edit in the self-guard follows the self-guard.
- **Every other hold is a defect:** a rule, skill, label or gate holding non-production work for the owner is a defect. Do the work, then fix the hold. `ws_owner_scope` fails on it.

## Runtime safety

- **Reason from the worst case.** For environment changes, wrappers, redirection, or interception rules, check for no-TTY deadlock in CI or child processes, concurrent shared-file truncation/races, and network or cold-start failure cascades. Reject a proposal whose lack of backlash cannot be established.
- **Treat three hidden green failures as defects:** WRONG FORMULA (an incorrect formula passes assertions), GREEN-WHILE-EMPTY (filtering removes all output but reports success), and STALE-REPORTED-AS-FRESH (old data is labeled fresh). Implausible output is evidence of a defect.
- **Protect ambient services.** Default unit tests and subagent tasks must not destructively act on host ports, shared background processes, or development databases (`DROP`, `TRUNCATE`, `--clear`, forced restart). Resets require an isolated sandbox/worktree with a dedicated random port, or an explicit `CI=true` or `ALLOW_CLEAR_TEST=1` guard; otherwise skip safely with a warning.
- **Two triggers:** Every background job or batch process needs both scheduled execution and manual replay.
- **Do not steal CD locks:** A trigger is instant but publication is delayed. Do not interrupt a running deployment; the next run must coalesce commits accumulated while it was busy.

# Finance Report — Agent & Contributor Guide

> **Rule source**: Generated from `dev_env`; pass the rule-text checklist rather than hand-editing.
> **Merge authority**: Deliverable = CI-passing PR merged autonomously when [docs/contributing/branch-policy.md](docs/contributing/branch-policy.md) §4 holds. Gate code, workflows, and release code merge after the independent review required by Root section `Production reservation`.
> **Production here**: the infra2 workflow `reconcile-iac-inputs.yml` with `promote_prod=true` and the infra2 workflow `deploy.yml` with `type=prod`.
> **Checklist & Language**: Check [docs/agents/orchestration.md](docs/agents/orchestration.md) before finishing. Write code, PRs, commits, issues, and docs in **English**.

## Security & Red Lines

Full rules: **[docs/agents/red-lines.md](docs/agents/red-lines.md)**

- **NEVER** use `float` for monetary amounts — use `Decimal`.
- **NEVER** commit `.env`, `*.pem`, or credential files, or skip entry balance validation.
- **NEVER** use raw `fetch()` in frontend — use `lib/api.ts`.
- **NEVER** create `sa.Enum` without explicit `name="..."`.

## Mandatory Work Order & SSOT

- **Work order:** **MECE → User Case → Test → Code → Doc** (`common/meta/flows/user_cases_ssot.json` + EPIC in `docs/project/` — never mirror test tables into `docs/project/EPIC-*.md`; failing tests first; minimal code; update owning `common/<pkg>/readme.md`). Details: [docs/agents/orchestration.md](docs/agents/orchestration.md), [common/testing/tdd.md](common/testing/tdd.md).
- **SSOT first:** Define bounded-context concepts in `common/<pkg>/readme.md` (and cross-cutting metadata in `common/*/data/` or `common/runtime/`); `docs/ssot/` is retired (#1823). Layering registry: [common/meta/readme.md](common/meta/readme.md).
- **Pre-push gate parity:** `git push` runs `tools/preflight.py --tier=static` automatically via `pre-commit` (install hooks with `make install`; never invoke `moon run :lint && moon run :test` before every push — run focused tests locally and `--tier=static`, leaving full suites to CI).
- **Quality board & invariant core:** Track CI timing, coverage, and nightly audit freshness at [finance_report/board/](https://wangzitian0.github.io/finance_report/board/). Preserve the L3 invariant core in [common/testing/invariant_core.py](common/testing/invariant_core.py) (`pytest -m invariant_core`).

## Branch, PR, and Merge Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- No direct commits to `main`. Conflict-free PRs (`MERGEABLE`, `CLEAN` or `BEHIND <= 24h`) merge without rebasing; rebase only on `DIRTY` conflicts or `> 24h` behind `main`.
- **Weighted review gate:** Unresolved review threads use literal `severity:` weights (`high = 1.0`, `middle`/`medium = 0.5`, `low = 0.25`, unlabelled = `0.5`); `>= 1.0` blocks (`check_pr_review_threads.py` & `ws-pr-gate`). Reply with evidence before resolving; Copilot review is optional and non-blocking.
- A merge that reaches **production** is a production change (Root section `Production reservation`). Only a production change waits for the user. Protected files follow the checklist in [branch-policy.md](docs/contributing/branch-policy.md) §4.
- Sub-issues close once Stage 1 merges and a passing `smoke` reality probe completes (`ws-delivery-status --assert-complete --reality-probe`); `infra2` `release-train` handles Staging verification and `[PROD GATEKEEPER]` (`deploy vX.Y.Z`).
- Use `ws-pr-gate` or GitHub events for open PRs (no foreground watch loops). Add `_issue<N>_` worktree naming (`finance_report_issue1234_infra`), PR title scope `[$(basename ...)] ...`, and keep `ongoing` on open PRs only.

## Agent Architecture & Writing

- Orchestrate in the host runtime's main loop and delegate read-only searches or isolated edits to host-native subagents per Root. Skills: **[.agents/skills/](.agents/skills/)**.
- **UI proof:** Before/after `ux-review` captures pass on simulator or browser with an independent read-only check before any UI change reaches production.
- **Plain facts & performance:** State exact files, commands, exit codes, and year-scale control-sampled metrics when claiming latency improvements. Avoid banned jargon (`orthogonal`, `ontology planes`, `terminal residue`, `epistemic layer`, `emergence`, `empowerment`, `touchpoint`, `paradigm shift`).

## Load on demand

| Topic | Read |
|---|---|
| Repo overview & stack | [`README.md`](README.md) · [`vision.md`](vision.md) |
| Package hierarchy & schema | [`common/meta/readme.md`](common/meta/readme.md) · [`common/meta/schema.md`](common/meta/schema.md) |
| Dev commands & environments | [`common/meta/development.md`](common/meta/development.md) · [`common/runtime/environments.md`](common/runtime/environments.md) |
| CI & Deployment | [`common/testing/ci-cd.md`](common/testing/ci-cd.md) · [`common/runtime/deployment.md`](common/runtime/deployment.md) |
| Agent orchestration & red lines | [`docs/agents/orchestration.md`](docs/agents/orchestration.md) · [`docs/agents/red-lines.md`](docs/agents/red-lines.md) |
<!-- WS_STATIC_END -->
