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
4. **No agent merge authority**: Agents may open PRs and monitor CI, but only the user may merge them.
5. **One task per branch**: Keep each branch scoped to its requested issue or change set.

---

## 🔧 Pre-commit Hooks (REQUIRED for contributors)

Before your first commit, install pre-commit hooks to prevent CI failures:

```bash
make install          # Runs scripts/bootstrap.sh
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
| `moon run :test` | All tests (90% backend coverage) |
| `moon run :test -- --fast` | TDD mode (no coverage, fastest) |
| `moon run :test -- --e2e` | E2E tests (Playwright) |
| `moon run :build` | Build all |

Full reference: [docs/ssot/development.md](../ssot/development.md)

---

## 🔍 Debugging & Observability

**Use `scripts/debug.py` for unified debugging** across all environments.

```bash
# View logs (auto-detects environment)
python scripts/debug.py logs backend
python scripts/debug.py logs frontend --tail 100

# Specify environment explicitly
python scripts/debug.py logs backend --env staging
python scripts/debug.py logs frontend --env production

# Check service status
python scripts/debug.py status backend --env staging
```

**Log retention**:
- Docker logs: 50MB per container (size-based rotation, short-term only)
- SigNoz: Long-term retention (centralized, queryable at `https://signoz.zitian.party`)

Query logs by service:
```
service_name = "finance-report-backend"
deployment.environment = "production"  # or "staging", "pr-47"
```

Full observability reference: [docs/ssot/observability.md](../ssot/observability.md)

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
4. Run `python scripts/check_env_keys.py` to verify

**Variable classification**:
- **Required** (`secrets.ctmpl`): `DATABASE_URL`, `S3_*`
- **Optional** (`config.py` defaults): `DEBUG`, `BASE_CURRENCY`, `AI_PROVIDER`, `ZAI_API_KEY`, `AI_BASE_URL`, `PRIMARY_MODEL`, `OCR_MODEL`, `VISION_MODEL`, `AI_JSON_TIMEOUT_SECONDS`, `AI_JSON_MAX_TOKENS`, `AI_JSON_DISABLE_THINKING`, `REDIS_URL`
- **Infrastructure** (direnv managed): `DOKPLOY_*`, `VAULT_*`, `VPS_*`

Full reference: [docs/ssot/development.md](../ssot/development.md)

---

## Related

- [docs/ssot/development.md](../ssot/development.md) — Full development environment setup
- [docs/agents/orchestration.md](../agents/orchestration.md) — Agent workflow and STAR framework
- [docs/agents/red-lines.md](../agents/red-lines.md) — Security rules
- [AGENTS.md](../../AGENTS.md) — Top-level routing
