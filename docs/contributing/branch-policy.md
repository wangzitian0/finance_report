# Contributor Branch Policy

> **SSOT Key**: `branch_policy`
> **Audience**: Human contributors and AI agents.
> Defines Git branch rules, pre-commit hooks, and environment setup.

---

## 🌿 Branch Management Rules (CRITICAL)

1. **NO commits to `main`**: All changes must go through branches and PRs.
2. **Parallel PRs are allowed**: An open PR does not block a new branch. The checklist in rule 3 decides.
3. **Branch creation is the agent's decision**: A branch is reversible and is not a production action. No permission is needed. Create a branch when all of the following hold:
   - The branch advances one issue, and the issue is claimed (assignee or start comment).
   - No other open PR advances the same issue.
   - Parallel branches do not write the same files or generated outputs.
4. **Agent merge authority** (owner instruction, 2026-10-06): Only a **production** deployment needs the owner's approval and presence. An agent merges any other PR when **all** of the following hold. If the agent cannot verify one condition, it fails closed and does not merge.
   - Required checks are green on the **exact head SHA being merged**, not on an earlier one.
   - Every actionable review thread is resolved — human reviewer, Copilot, or `/code-review` alike. An actionable finding requests a concrete code, documentation, test, or process change; questions and informational comments do not count.
   - The protected-file checklist below holds for every protected file the PR touches. No owner quote is needed.
   - Merging does not reach **production**, and triggers no other irreversible side effect. Scope this by environment, not by "any deploy":
     - The automatic `report-branch-main` **preview** redeploy never blocks agent merge. `.github/workflows/notify-infra2.yml` dispatches it after every green `main` CI run.
     - A **staging** deploy (`.github/workflows/deploy.yml`, manual `workflow_dispatch`) is the agent's to trigger.
     - **Production** is gated. It deploys only through the separate, manual `.github/workflows/release.yml` (`workflow_dispatch` on a pinned `version_ref` release tag).
     - Dispatching `release.yml` with `dry_run=false` needs the owner's approval and presence for that `version_ref`. Any other action that promotes a head SHA to production needs the same approval.
     - Approval for one `version_ref` does not carry over to another.
     - `release.yml` with `dry_run=true` does not mutate production. The agent may run it.
   - The PR description's checklist is complete, and the PR references the issue it advances (or states `None`).

   **Protected-file checklist.** Each protected file has its own checklist instead of an owner quote:

   | File | Checklist |
   |------|-----------|
   | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | These files are generated from dev_env. Do not hand-edit them. Change the dev_env rule source, then re-render. The publish manifest `.ws-publish/manifest.json` records the SHA-256 of each generated file. dev_env `ws-check-drift` guards the generated files. This repository has no CI job that compares them with the manifest. |
   | `README.md`, `vision.md` | The normal review checklist applies: required checks are green on the head SHA, and every actionable review thread is resolved. |

   `common/meta/extension/check_ssot_ownership.py` does not enforce this list. That script exempts these files from its rule-keyword cross-reference check (`CHECK4_EXEMPT_PATHS`) and checks nothing else about them.

   A PR that fails a condition is not ready to merge. The agent fixes the cause until every condition holds. Only a production deployment waits for the owner.
5. **One task per branch**: Keep each branch scoped to its requested issue or change set.

---

## 🔧 Pre-commit Hooks (REQUIRED for contributors)

Before your first commit, install pre-commit hooks to prevent CI failures:

```bash
make install          # Runs tools/bootstrap.sh
# OR manually:
uvx pre-commit install
```

**What hooks do**:

1. **Ruff lint + format** — Auto-fixes Python style issues
2. **Env var consistency** — Validates `secrets.ctmpl` ↔ `config.py` ↔ `.env.example`
3. **File hygiene** — Trailing whitespace, merge conflicts, large files
4. **Branch protection** — Prevents direct commits to `main`

---

## 🌙 Moon Commands (Quick Reference)

| Command | Purpose |
|---------|---------|
| `moon run :dev -- --backend` | Full Stack (App + DB + Redis + MinIO) |
| `moon run :dev -- --frontend` | Next.js on :3000 |
| `moon run :lint` | Lint all |
| `moon run :lint -- --fix` | Auto-fix Python |
| `moon run :test` | All tests (backend threshold code-owned by `apps/backend/pyproject.toml`) |
| `moon run :test -- --fast` | TDD mode (no coverage, fastest) |
| `moon run :test -- --e2e` | Root deployment E2E tests |
| `moon run :test -- --backend-e2e` | Backend Tier-1 API E2E tests |
| `moon run :build` | Build all |

Full reference: [common/meta/development.md](../../common/meta/development.md)

---

## 🔍 Debugging & Observability

**Use `tools/debug.py` for unified debugging** across all environments.

```bash
# View logs (auto-detects environment)
python tools/debug.py logs backend
python tools/debug.py logs frontend --tail 100

# Specify environment explicitly
python tools/debug.py logs backend --env staging
python tools/debug.py logs frontend --env production

# Check service status
python tools/debug.py status backend --env staging
```

**Log retention**:
- Docker logs: 50MB per container (size-based rotation, short-term only)
- the observability backend: Long-term retention (centralized, queryable at `https://signoz.zitian.party`)

Query logs by service:
```
service_name = "finance-report-backend"
deployment.environment = "production"  # or "staging", "pr-47"
```

Full observability reference: [common/observability/observability.md](../../common/observability/observability.md)

---

## 🛡️ Environment Variable Rules

**Three-layer SSOT** (all three must stay in sync):
- `secrets.ctmpl` → Staging/Prod required keys (Vault)
- `.env.example` → Complete variable documentation
- `apps/backend/src/config.py` → Type definitions + defaults

**Adding new variables**:
1. Add to `secrets.ctmpl` (if required for production)
2. Add to `config.py` (with type and default)
3. Update `.env.example` (with classification comment)
4. Run `python tools/check_env_keys.py` to verify

**Variable classification**:
- **Required** (`secrets.ctmpl`): `DATABASE_URL`, `S3_*`
- **Optional** (`config.py` defaults): `DEBUG`, `BASE_CURRENCY`, `AI_PROVIDER`, `ZAI_API_KEY`, `AI_BASE_URL`, `PRIMARY_MODEL`, `OCR_MODEL`, `VISION_MODEL`, `AI_JSON_TIMEOUT_SECONDS`, `AI_JSON_MAX_TOKENS`, `AI_JSON_DISABLE_THINKING`, `REDIS_URL`
- **Infrastructure** (direnv managed): `DOKPLOY_*`, `VAULT_*`, `VPS_*`

Full reference: [common/meta/development.md](../../common/meta/development.md)

---

## Related

- [common/meta/development.md](../../common/meta/development.md) — Full development environment setup
- [docs/agents/orchestration.md](../agents/orchestration.md) — Agent workflow and STAR framework
- [docs/agents/red-lines.md](../agents/red-lines.md) — Security rules
- [AGENTS.md](https://github.com/wangzitian0/finance_report/blob/main/AGENTS.md) — Top-level routing
