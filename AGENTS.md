# Finance Report — Agent & Contributor Guide

> **Prohibition**: AI may NOT modify this file without explicit authorization.
> **Prohibition**: AI deliverable = CI-passing PR. User reviews and decides whether to merge.
> **Checklist**: Before completing a task, verify every item in [docs/agents/orchestration.md](docs/agents/orchestration.md).
> **Language**: All code, PRs, commits, and reports must be in **English**.

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
| **SSOT** (`docs/ssot/`) | *In what shared language* — the canonical base elements, vocabulary, and contracts that everything else reuses | common dictionary |
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

`docs/ssot/` is the **authoritative source for the shared base elements and
contracts** — the common language the rest of the repo reuses. It does not own
goals (vision / EPICs) or module design (READMEs); it owns the *terms* they
speak in.  
The SSOT ownership map is: **[docs/ssot/MANIFEST.yaml](docs/ssot/MANIFEST.yaml)**

1. **No SSOT, no work**: Define the shared terms in `docs/ssot/` before writing code.
2. **No hidden drift**: When code differs from SSOT, sync immediately.
3. **Single owner**: Each concept has exactly one SSOT file; see MANIFEST.

---

## 🔄 Mandatory Work Order

**EPIC → ACx.y.z → Test → Code → Doc**

0. Frame the work with a **MECE** breakdown: mutually exclusive task slices, collectively exhaustive coverage of the stated goal, explicit dependencies, and explicit out-of-scope items.
1. Anchor to an EPIC in `docs/project/`
2. Register ACs in `docs/ac_registry.yaml` (feature) or `docs/infra_registry.yaml` (infra)
3. Write **failing** tests referencing AC IDs (🔴 red)
4. Write minimal code to pass tests (🟢 green)
5. Update SSOT docs

Details: [docs/agents/orchestration.md](docs/agents/orchestration.md) · [docs/ssot/tdd.md](docs/ssot/tdd.md)

---

## 🌿 Branch & PR Rules

Full policy: **[docs/contributing/branch-policy.md](docs/contributing/branch-policy.md)**

- ❌ No direct commits to `main`
- ✅ User-approved parallel PR branches are allowed
- ❌ Agents never merge PRs
- ✅ Install pre-commit hooks: `make install`
- ✅ Run `moon run :lint && moon run :test` before pushing
- ✅ A mergeable PR must resolve all Copilot auto-review comments (either by fixing them or providing a justification for not doing so). Once resolved, resolve the comment threads on GitHub.
- ✅ For implementation work, the final deliverable is not complete until a ready PR is pushed and the final report includes PR URL, branch, commit SHA, draft status, `mergeable`, `mergeStateStatus`, and required-check summary.
- ✅ If GitHub does not report `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`, the task is not a mergeable-PR delivery; report the blocker, the failing/pending check or review thread, and the next action instead of calling the work complete.

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

Full guide: **[docs/agents/orchestration.md](docs/agents/orchestration.md)**

| Agent | Cost | When |
|-------|------|------|
| **Sisyphus** | — | Main orchestrator |
| `explore` | FREE | Parallel codebase exploration |
| `librarian` | FREE | External docs |
| `frontend-ui-ux-engineer` | MEDIUM | Mandatory for CSS/styling |
| `multimodal-looker` | MEDIUM | Image/PDF |
| `oracle` | EXPENSIVE | Architecture decisions |

Skills: [.opencode/skills/](.opencode/skills/) · Config: [.opencode/oh-my-openagent.json](.opencode/oh-my-openagent.json)

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
| **SSOT** | `docs/ssot/` | Shared base-element language & contracts |
| **Project EPICs** | `docs/project/` | Horizontal (cross-module) goals & tracking |
| **Module READMEs** | `apps/*/README.md` | Per-module goal & design guide |
