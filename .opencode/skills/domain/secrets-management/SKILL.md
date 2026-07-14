---
name: secrets-management
description: Environment variables, secrets management, multi-environment strategy using Vault, Dokploy, and direnv. Use this skill when working with configuration, secrets, environment setup, or deployment pipelines.
---

# Secrets & Environment Management

Operational how-to only. The **contracts live elsewhere** — read the owner, do
not restate it here (#1658):

- Three-layer secret contract (Vault `secrets.ctmpl` → `config.py` →
  `.env.example`), vault-agent injection flow, and cross-repo seam →
  [`common/runtime/deployment.md`](../../../../common/runtime/deployment.md)
- Environment taxonomy (names, suffixes, isolation) →
  [`common/runtime/environments.md`](../../../../common/runtime/environments.md)
- CI gates on env consistency → [`common/testing/ci-cd.md`](../../../../common/testing/ci-cd.md)
- Env-var red lines (`NEXT_PUBLIC_` Dockerfile bake, config.py typing) →
  [`docs/agents/red-lines.md`](../../../../docs/agents/red-lines.md)

Vault path convention: `secret/data/{project}/{environment}/{component}`
(e.g. `secret/data/finance_report/production/app`).

---

## Credentials cheat-sheet

| Credential | Purpose | Scope | Storage |
|------------|---------|-------|---------|
| `VAULT_ROOT_TOKEN` | Admin operations only | All paths, write | 1Password (`op://Infra2/.../Token`) |
| `VAULT_ROLE_ID` + `VAULT_SECRET_ID` | Runtime AppRole login → secret reading | Read-only, per-project/env/service | Dokploy ENV per service (injected by `invoke vault.setup-approle`) |
| `VAULT_ADDR` | vault-agent connect address | Non-secret but **required** (missing → agent hangs / service crash-loops on "Waiting for secrets") | Dokploy project-level ENV |
| `VAULT_APP_TOKEN` *(legacy)* | Retired for runtime auth; only checked for non-AppRole composes | Unused today | Dokploy ENV — legacy fallback only |

- **Never** use `VAULT_ROOT_TOKEN` in application containers.
- AppRole creds are injected by infra2 into each service's Dokploy ENV — never
  in `.envrc`, a local `.env`, or committed anywhere. Never shared across
  services.
- Infra automation vars (`DOKPLOY_API_KEY`, `VAULT_ADDR`, `VPS_HOST`) are
  direnv/CI-managed, not application config.

---

## Workflow: adding a new variable

1. Required in production? → add to the service's `secrets.ctmpl` (in `repo/`,
   requires an infra2 PR). Optional? → skip the template.
2. Add to `apps/backend/src/config.py` with type + default
   (`Field(validation_alias=...)`).
3. Add to `.env.example` with a comment (`[VAULT]` marker if
   production-managed).
4. Validate: `python tools/check_env_keys.py --diff` (the CI gate).
5. Production secret? → `vault kv put secret/data/finance_report/{env}/app ...`
   and sync the `repo/` submodule pointer in the same PR.

Frontend: `NEXT_PUBLIC_*` values are frozen at build time — they must be
`ARG`+`ENV` in `apps/frontend/Dockerfile` (red line).

---

## Debugging environment issues

Check the sources in order:

```bash
cat .env | grep <VAR>                                      # 1. local file
python tools/debug.py status backend --env production      # 2. Dokploy ENV
vault kv get secret/data/finance_report/production/app     # 3. Vault
docker exec finance-report-backend env | grep <VAR>        # 4. container runtime
```

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Variable not found | Missing in secrets.ctmpl | Add to template + update Vault |
| Vault render failed / "Waiting for secrets" timeout | `ENV` or `VAULT_ADDR`/AppRole creds missing in container | Fix the Dokploy ENV, re-run `invoke vault.setup-approle` if creds absent |
| `NEXT_PUBLIC_` empty in browser | Not in Dockerfile ARG | Add ARG + ENV, rebuild |
| CORS error | CORS_ORIGINS mismatch | Update in Vault + redeploy |
| Variable not updating | Vault updated but container not restarted / stale Dokploy ENV | Redeploy the release tag |

Runtime validation: `moon run :dev -- --check` (boot checks DB/S3/Redis/AI
key); `--critical-only` for the CI flavor.

---

## Operational playbooks

### Change a production secret

```bash
export VAULT_ADDR=https://vault.zitian.party
export VAULT_ROOT_TOKEN=$(op read 'op://Infra2/.../Token')
vault kv put secret/data/finance_report/production/app KEY="value" ...
# Restart = re-run the fixed production deploy for the CURRENT release tag:
cd repo && python -m tools.deploy_v2 --service finance_report/app --type prod \
  --version-ref vX.Y.Z --iac-ref "$(git rev-parse HEAD)" \
  --domain zitian.party --staging-validated --code-reviewed
python tools/debug.py logs backend --env production --tail 20   # verify
```

### Rotate the JWT secret

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
vault kv patch secret/data/finance_report/production/app SECRET_KEY="<new>"
# Rolling restart via deploy_v2 (same as above). Old tokens stay valid until
# ACCESS_TOKEN_EXPIRE_MINUTES elapses — verify an old bearer still works.
```

### Add a new environment

Register the environment in infra2's service registry first, then deploy via
the `deploy_v2` front door (never the retired app-side Dokploy bash path).
Create its Vault path (`secret/data/finance_report/<env>/app`) and set `ENV`
in the Dokploy compose.

---

## The Proof

```bash
python tools/check_env_keys.py --diff        # layer consistency (CI gate)
moon run :dev -- --check                     # runtime boot validation
vault kv get secret/data/finance_report/production/app   # keys present
cd apps/frontend && npm run build && grep -r "NEXT_PUBLIC_APP_URL" .next/static
```
