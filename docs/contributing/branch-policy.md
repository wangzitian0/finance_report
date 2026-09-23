# Contributor Branch Policy

> **SSOT Key**: `branch_policy`
> **Audience**: Human contributors and AI agents.
> Defines Git branch rules, pre-commit hooks, and environment setup.

---

## 🌿 Branch Management Rules (CRITICAL)

1. **NO commits to `main`**: All changes must go through branches and PRs.
2. **User-approved parallel PRs are allowed**: Agents may create a new branch while another PR is open when the user explicitly asks for a separate PR.
3. **Explicit permission required**: Only create a new branch when:
   - Current PR is merged, OR
   - User explicitly requests a new branch or PR, OR
   - Previous task is explicitly completed.
4. **Conditional agent merge authority**: An agent may merge a PR only when **all** of the following hold. Any one of them unverifiable means fail closed — do not merge.
   - Required checks are green on the **exact head SHA being merged**, not on an earlier one.
   - Every actionable review thread is resolved — human reviewer, Copilot, or `/code-review` alike. An actionable finding requests a concrete code, documentation, test, or process change; questions and informational comments do not count.
   - The PR touches no protected file (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `README.md`, `vision.md` — the list `common/meta/extension/check_ssot_ownership.py` enforces).
   - Merging must not reach **production**, and must trigger no other irreversible side effect. Scoped by environment, not by "any deploy": the automatic `report-branch-main` **preview** redeploy that `.github/workflows/notify-infra2.yml` dispatches after every green `main` CI run is expected and never blocks agent merge; a **staging** deploy (`.github/workflows/deploy.yml`, manual `workflow_dispatch`) is likewise the agent's to trigger. Only **production** is gated — it deploys exclusively through the separate, manual `.github/workflows/release.yml` (`workflow_dispatch` on a pinned `version_ref` release tag) — dispatching that workflow, or any action that otherwise promotes this head SHA to production, needs the owner's approval first.
   - The PR description's checklist is complete, and the PR references the issue it advances (or states `None`).

   A PR that fails any condition is still the agent's to prepare and the user's to merge. A PR that modifies a protected file or whose merge would reach production needs the user's **explicit approval of that head SHA** — an approval of an earlier head does not carry over.
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
