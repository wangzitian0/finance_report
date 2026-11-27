# Finance Report — Agent & Contributor Guide

> **Rule source**: This repository owns its own `AGENTS.md` directly.
> **Merge authority**: Deliverable = CI-passing PR merged autonomously when [docs/contributing/branch-policy.md](docs/contributing/branch-policy.md) §4 holds. Gate code, workflows, and release code merge after the independent review required by `Production reservation`.
> **Production here**: the infra2 workflow `reconcile-iac-inputs.yml` with `promote_prod=true`.
> **Checklist & Language**: Check [docs/agents/orchestration.md](docs/agents/orchestration.md) before finishing. Write code, PRs, commits, issues, and docs in **English**.

## Production reservation

The single definition of the production reservation. Other tiers, skills and gates point here.

- **Only a production change returns to the owner.** A production change alters what production runs or stores (deploy, promote or apply to production; production secret write; manual production data write or deletion; production DNS, route or host change; unrecallable release; or scheduled unapproved production code). Each Repo tier names its production paths. A path can be a merge or a release-checkout pull.
- **Approval:** the owner approves the exact commit SHA or release tag of each production change, and is present when it runs. A "deploy" reply covers only the release that it names. Immediately before a production dispatch, get a live reply from the owner.
- **Self-guard:** an edit that removes, narrows or redefines the production reservation needs the owner's approval of its head SHA. This includes an edit that makes fewer production runs wait for the owner (deploy-path approval check, production job classification, or production environment settings). It also covers removing or weakening a pin of this section, its pin test, or the required check that runs the test.
- **Everything else is the agent's:** in any repository the owner owns, every non-production change (including `dev_env` outside the self-guard), staging and canary deploy, release tag, rule text, skill, gate/release code, and required-check edit. Before merging gate or release code, an independent read-only reviewer inspects the head SHA and states whether the gate gets stricter, equal or looser. A looser edit in the self-guard follows the self-guard.
- **Every other hold is a defect:** a rule, skill, label or gate holding non-production work for the owner is a defect. Do the work, then fix the hold. `ws_owner_scope` fails on it.

## Security & Red Lines

Full rules: **[docs/agents/red-lines.md](docs/agents/red-lines.md)**

- **NEVER** use `float` for monetary amounts — use `Decimal`.
- **NEVER** commit `.env`, `*.pem`, or credential files, or skip entry balance validation.
- **NEVER** use raw `fetch()` in frontend — use `lib/api.ts`.
- **NEVER** create `sa.Enum` without explicit `name="..."`.

## Mandatory Work Order & SSOT

- **Work order:** **MECE → User Case → Test → Code → Doc** (`common/meta/flows/user_cases_ssot.json` + EPIC in `docs/project/` — never mirror test tables into `docs/project/EPIC-*.md`; failing tests first; minimal code; update owning `common/<pkg>/readme.md`). Details: [docs/agents/orchestration.md](docs/agents/orchestration.md), [common/testing/tdd.md](common/testing/tdd.md).
- **SSOT first:** Define bounded-context concepts in `common/<pkg>/readme.md` (and cross-cutting metadata in `common/*/data/` or `common/runtime/`); `docs/ssot/` is retired (#1823). Layering registry: [common/meta/readme.md](common/meta/readme.md).
- **Pre-push gate parity:** `git push` runs `python -m common.testing.preflight --tier=static` automatically via `pre-commit` (install hooks with `make install`; run focused tests locally and `--tier=static`, leaving full suites to CI).
- **Quality board & invariant core:** Track CI timing, coverage, and nightly audit freshness at [finance_report/board/](https://wangzitian0.github.io/finance_report/board/). Preserve the L3 invariant core in [common/testing/invariant_core.py](common/testing/invariant_core.py) (`pytest -m invariant_core`).

## Branch, PR, and Merge Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- No direct commits to `main`. Conflict-free PRs (`MERGEABLE`, `CLEAN` or `BEHIND <= 24h`) merge without rebasing; rebase only on `DIRTY` conflicts or `> 24h` behind `main`.
- **Weighted review gate:** Unresolved review threads use literal `severity:` weights (`high = 1.0`, `middle`/`medium = 0.5`, `low = 0.25`, unlabelled = `0.5`); `>= 1.0` blocks (`python -m common.testing.check_pr_review_threads` & `ws-pr-gate`). Reply with evidence before resolving; Copilot review is optional and non-blocking.
- A merge that reaches **production** is a production change (Root section `Production reservation`). Only a production change waits for the user. Protected files follow the checklist in [branch-policy.md](docs/contributing/branch-policy.md) §4.
- Sub-issues close once Stage 1 merges and a passing `smoke` reality probe completes (`ws-delivery-status --assert-complete --reality-probe`); `infra2` `release-train` handles Staging verification and `[PROD GATEKEEPER]` (`deploy vX.Y.Z`).
- Use `ws-pr-gate` or GitHub events for open PRs (no foreground watch loops). Add `_issue<N>_` worktree naming (`finance_report_issue1234_infra`), PR title scope `[$(basename ...)] ...`, and keep `ongoing` on open PRs only.

## Agent Architecture & Writing

- Orchestrate in the host runtime's main loop and delegate read-only searches or isolated edits to host-native subagents per Root. Skills: **[.agents/skills/](.agents/skills/)** (mirrored in `.claude/skills/`).
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
