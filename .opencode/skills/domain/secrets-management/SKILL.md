---
name: secrets-management
description: Environment variables, secrets management, multi-environment strategy using Vault, Dokploy, and direnv. Use this skill when working with configuration, secrets, environment setup, or deployment pipelines.
---

# Secrets & Environment Management

Operational how-to only. The **contracts live elsewhere** — read the owner, do
not restate it here (#1658):

- App secret contract (`config.py` → generated `.env.example` and
  `required-env.generated.json`), vault-agent injection flow, and cross-repo seam →
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
| `VAULT_TOKEN` (iac-runner only) | Deploy-time secret supply: copies `human` values from 1Password into Vault, generates `runtime` ones, restarts agent + app when a value changed | Bounded, short-TTL, minted in-container by AppRole login; handed to `invoke *.sync` | iac-runner process env only — never in Finance Report CI, `.envrc`, a local `.env`, or 1Password |
| `VAULT_ROLE_ID` + `VAULT_SECRET_ID` | Runtime AppRole login → secret reading | Read-only, per-project/env/service | Dokploy ENV per service (injected by infra2's `invoke vault.setup-approle`) |
| `VAULT_ADDR` | vault-agent connect address | Non-secret but **required** (missing → agent hangs / service crash-loops on "Waiting for secrets") | Dokploy project-level ENV |
| `VAULT_APP_TOKEN` *(legacy)* | Retired for runtime auth; only checked for non-AppRole composes | Unused today | Dokploy ENV — legacy fallback only |

- Nobody on the Finance Report side ever uses `VAULT_ROOT_TOKEN`: it is infra2's
  bootstrap-only credential (`bootstrap/05.vault`, AppRole + policy setup).
  Application containers, Finance Report CI, and every playbook below hold no
  Vault token at all.
- Human-issued values (a third-party API key such as `ZAI_API_KEY`) go into
  1Password (`Infra2` vault, item `finance_report/{env}/app`); the next deploy's
  secret supply copies them into Vault. Nobody types into Vault — a direct write
  is break-glass and infra2's daily reconcile reports it as drift.
- AppRole creds are injected by infra2 into each service's Dokploy ENV — never
  in `.envrc`, a local `.env`, or committed anywhere. Never shared across
  services.
- Infra automation vars (`DOKPLOY_API_KEY`, `VAULT_ADDR`, `VPS_HOST`) are
  direnv/CI-managed, not application config.

---

## Workflow: adding a new variable

1. Add to `apps/backend/src/config.py` with type + default
   (`Field(validation_alias=...)`).
2. Regenerate `.env.example` and `common/runtime/required-env.generated.json`.
3. Validate: `python tools/check_env_keys.py --diff` (the CI gate).
4. Name its producer in `config.ENV_SOURCE_CLASSES` (a side table, so no public
   `Field()` changes): `human` → the operator puts the value in 1Password and the
   deploy copies it into Vault; `runtime` → the deploy generates it; `decision` →
   infra2 states it in the compose env for `finance_report/app` (needs an infra2
   compose PR); unlisted → `code` default, never stored. Regenerate the manifest
   (`python tools/generate_env_reference.py`): infra2 renders its vault-agent
   template and policy from it, so there is no hand-written `secrets.ctmpl` to
   edit and no git pointer to update here.

Frontend: `NEXT_PUBLIC_*` values are frozen at build time — they must be
`ARG`+`ENV` in `apps/frontend/Dockerfile` (red line).

---

## Debugging environment issues

Check the sources in order:

```bash
cat .env | grep <VAR>                                      # 1. local file
python tools/debug.py status backend --env production      # 2. Dokploy ENV
# 3. Vault (masked; infra2 repo, bounded token — never the root token):
invoke env.list-all --project=finance_report --service=app
docker exec finance-report-backend env | grep <VAR>        # 4. container runtime
```

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Variable not found | Wrong/missing source class in `config.ENV_SOURCE_CLASSES` (a `code` default is never rendered; a `decision` value must be in infra2's compose env) | Fix the class, regenerate the manifest; infra2 re-renders the template from it |
| Vault render failed / "Waiting for secrets" timeout | `ENV` or `VAULT_ADDR`/AppRole creds missing in container | Fix the Dokploy ENV; infra2 re-runs `invoke vault.setup-approle` if creds absent |
| `NEXT_PUBLIC_` empty in browser | Not in Dockerfile ARG | Add ARG + ENV, rebuild |
| CORS error | `CORS_ORIGINS` mismatch — a `decision` value stated in infra2's compose env, not in Vault | Change it in the infra2 compose / `compose_env_overrides` and redeploy |
| Variable not updating | Vault updated but container not restarted / stale Dokploy ENV | Redeploy the release tag |

Runtime validation: `moon run :dev -- --check` (boot checks DB/S3/Redis/AI
key); `--critical-only` for the CI flavor.

---

## Operational playbooks

### Change a production `human` secret (e.g. `ZAI_API_KEY`)

Human values live in 1Password; the deploy copies them into Vault. No Vault
token is involved at any step on the Finance Report side.

```bash
# 1. Put the new value in 1Password (Infra2 vault, item finance_report/production/app).
#    From the infra2 repo this writes 1Password only, never Vault:
invoke env.set KEY=VALUE --project=finance_report --env=production --service=app --type=root_vars
# 2. Redeploy the CURRENT release tag from this repo (release.yml workflow_dispatch).
#    infra2's secret supply — running in the iac-runner under its own bounded
#    VAULT_TOKEN — copies the changed value into Vault and restarts vault-agent + backend.
gh workflow run release.yml -f version_ref=vX.Y.Z
python tools/debug.py logs backend --env production --tail 20   # verify
```

### Rotate the JWT secret

`SECRET_KEY` is a `runtime` value: the deploy generated it once and it lives only
in Vault. Replacing it is the one sanctioned direct Vault write — break-glass, run
by an infra2 operator from the infra2 repo with a bounded token (never the root
token); the daily reconcile reports the write.

```bash
invoke env.set SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')" \
  --project=finance_report --env=production --service=app --break-glass
# Then redeploy the CURRENT release tag (release.yml, as above). Old tokens stay
# valid until ACCESS_TOKEN_EXPIRE_MINUTES elapses — verify an old bearer still works.
```

### Add a new environment

Register the environment in infra2's service registry first, then deploy via
the `deploy_v2` front door (never the retired app-side Dokploy bash path).
Put the `human` values in the 1Password item `finance_report/<env>/app`; the
first deploy's secret supply creates and fills
`secret/data/finance_report/<env>/app` (generating the `runtime` values) and
the compose sets `ENV` plus the `decision` values.

---

## The Proof

```bash
python tools/check_env_keys.py --diff        # layer consistency (CI gate)
moon run :dev -- --check                     # runtime boot validation
vault kv get secret/data/finance_report/production/app   # keys present
cd apps/frontend && npm run build && grep -r "NEXT_PUBLIC_APP_URL" .next/static
```
