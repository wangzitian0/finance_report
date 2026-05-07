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
- Business logic → [vision.md](vision.md)
- Moon commands / environment setup → [docs/ssot/development.md](docs/ssot/development.md)
- Six environments (naming, isolation) → [docs/ssot/environments.md](docs/ssot/environments.md)
- CI job structure / test strategy → [docs/ssot/ci-cd.md](docs/ssot/ci-cd.md)
- Deployment / Vault / staging → [docs/ssot/deployment.md](docs/ssot/deployment.md)
- Data model → [docs/ssot/schema.md](docs/ssot/schema.md)
- Current work → [docs/project/](docs/project/)

---

## 📐 SSOT-First Principle

The **sole authoritative source** is `docs/ssot/`.  
The SSOT ownership map is: **[docs/ssot/MANIFEST.yaml](docs/ssot/MANIFEST.yaml)**

1. **No SSOT, no work**: Define truth in `docs/ssot/` before writing code.
2. **No hidden drift**: When code differs from SSOT, sync immediately.
3. **Single owner**: Each concept has exactly one SSOT file; see MANIFEST.

---

## 🔄 Mandatory Work Order

**EPIC → ACx.y.z → Test → Code → Doc**

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
- ❌ No new branches while a PR is open
- ✅ Install pre-commit hooks: `make install`
- ✅ Run `moon run :lint && moon run :test` before pushing

---

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

Skills: [.opencode/skills/](.opencode/skills/) · Config: [.opencode/oh-my-opencode.json](.opencode/oh-my-opencode.json)

---

## 📅 Current Phase

**Phase 3–5** (Two-Stage Review · Reporting & AI · Portfolio Management)

Details: [docs/project/README.md](docs/project/README.md)

---

## 📁 Documentation Map

| Category | Path | Purpose |
|----------|------|---------|
| **Agent governance** | `docs/agents/` | Red lines, orchestration |
| **Contributor guide** | `docs/contributing/` | Branch policy, pre-commit |
| **SSOT** | `docs/ssot/` | Technical truth |
| **Project EPICs** | `docs/project/` | Task tracking |
| **Module READMEs** | `apps/*/README.md` | Per-app design guide |
