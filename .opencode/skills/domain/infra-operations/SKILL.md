---
name: infra-operations
description: Infrastructure operations, deployment, debugging, and monitoring. Use when deploying services, managing secrets, checking health, viewing logs, or troubleshooting infrastructure issues. Covers both finance_report app and infra2 platform components.
---

# Infrastructure Operations

> Operations guide for finance_report and infra2 platform.

## Prerequisites

```bash
# Initialize repo/ submodule (infra2)
git submodule update --init --recursive
cd repo && uv run invoke --list
```

---

## Tool Priority

1. **`deploy_v2` front door** — Required for staging/prod deploys.
   - GitHub workflow: `repo/.github/workflows/deploy.yml`
   - Local/manual equivalent: `cd repo && python -m tools.deploy_v2 ...`
2. **`invoke`** — Secrets, status, bootstrap, and targeted repair tasks.
3. **`tools/debug.py`** — Unified debugging.
4. **`libs` API** — Automation internals only.
5. **SSH** — Emergency investigation only (read-only).

Deploy identity is always `deploy_v2(service, type, version_ref, iac_ref)`.
`data_lane` is derived from the target environment; never pass data as an
operator input.

---

## Debug Commands

### Logs & Status

```bash
# View logs
python tools/debug.py logs backend [--env production] [--tail 50] [--follow]

# Check health
python tools/debug.py status backend --env production

# List containers
python tools/debug.py containers --env production

# SigNoz (historical)
python tools/debug.py logs backend --env production --method signoz
```

### Container Naming

⚠️ **Staging & Production use underscore**: `finance_report-{service}${ENV_SUFFIX}`
(from the infra2 IaC compose, not the local `docker-compose.yml`). DB service is
`postgres`, not `db`. SSOT: [environments.md](../../../docs/ssot/environments.md).

| Environment | Backend | PostgreSQL | Redis |
|-------------|---------|------------|-------|
| **Production** | `finance_report-backend` | `finance_report-postgres` | `finance_report-redis` |
| Staging | `finance_report-backend-staging` | `finance_report-postgres-staging` | `finance_report-redis-staging` |
| PR Preview | service DNS (no fixed name) | service DNS | service DNS |

**Critical**: For staging/prod, container name = hostname in the Dokploy network;
the backend's `DATABASE_URL`/`REDIS_URL` (from `10.app/secrets.ctmpl`) resolve to
these exact names. PR Preview raw compose drops fixed `container_name` and uses
compose service DNS.

**Note**: `tools/debug.py` (`CONTAINER_PATTERNS`) maps these underscore names for
staging/production and the hyphenated `finance-report-*` names for local/CI.
For production, use direct SSH: `ssh root@$VPS_HOST "docker logs finance_report-backend"`

---

## Invoke Commands

All commands from `repo/tasks.py`:

### Secrets (`env.*`)

```bash
invoke env.get DATABASE_URL                  # Defaults: project=platform, env=production
invoke env.get DATABASE_URL finance_report app production  # Full form: key first
invoke env.set DATABASE_URL "postgresql://..." finance_report app production
invoke env.list-all finance_report app production
```

### Deploy Front Door

```bash
cd repo

# App staging: pin both the app release and infra2 IaC ref.
python -m tools.deploy_v2 \
  --service finance_report/app \
  --type staging \
  --version-ref vX.Y.Z \
  --iac-ref vX.Y.Z \
  --domain zitian.party

# App prod: promote the same release tag after staging proof and code review.
python -m tools.deploy_v2 \
  --service finance_report/app \
  --type prod \
  --version-ref vX.Y.Z \
  --iac-ref vX.Y.Z \
  --domain zitian.party \
  --staging-validated \
  --code-reviewed

# Platform/backing service: artifact identity is the iac_ref-pinned stack.
python -m tools.deploy_v2 \
  --service platform/redis \
  --type staging \
  --iac-ref vX.Y.Z \
  --domain zitian.party
```

### Finance Report (`fr-*`)

```bash
invoke fr-app.status      # Check health
invoke fr-postgres.status # Check PostgreSQL
invoke fr-redis.status    # Check Redis
```

`fr-*.setup` tasks are lower-level bootstrap/repair tasks. They are not the
staging/prod deploy front door.

### Platform Services

Platform and backing services are `iac_pinned` deploy_v2 targets. Use
`--service platform/<name>` with `--type staging|prod` and a pinned `--iac-ref`.
Low-level setup tasks may still exist for bootstrap/repair internals, but they are
not the staging/prod deploy front door.

---

## Python APIs

> **Context**: These APIs are in `repo/` submodule (infra2).
> Run from `repo/` directory: `cd repo && python -c "from libs.env import ..."`

### Secrets (`libs/env.py`)

```python
from libs.env import get_secrets

secrets = get_secrets("finance_report", "app", "production")
print(secrets["DATABASE_URL"])
```

### Dokploy (`libs/dokploy.py`)

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose = client.get_compose("A6V-hbJlgHMwgPDoTDnhH")
compose_id = compose["composeId"]  # Extract ID
client.update_compose_env(compose_id, {"DEBUG": "true"})
```

Do not trigger deploys through the Dokploy client directly; use `deploy_v2` so
the coordinate, review/data red lines, rollout wait, and effective-config checks
run in one place.

### Deployer (`libs/deployer.py`)

```python
from libs.service_registry import service_attrs

services = service_attrs()
```

`Deployer` is an internal backend for platform sync and iac_runner. Operators
should invoke platform deploys through `deploy_v2` / iac_runner, not by calling
compose methods directly.

---

## Troubleshooting

### Container Not Found

**Symptoms**: `No such container`

**Fix**:
```bash
python tools/debug.py containers --env production
# Re-run the relevant deploy_v2 workflow/command for the affected service.
```

### Env Var Missing

**Symptoms**: `KeyError: 'DATABASE_URL'`

**Fix**:
```bash
invoke env.set DATABASE_URL "postgresql://..." finance_report app production
# Re-run the relevant deploy_v2 workflow/command so the service consumes the change.
```

### Deployment Failed

**Symptoms**: Deployment stuck

**Fix**:
```bash
python tools/debug.py logs backend --tail 100
# Fix issue, then:
cd repo && python -m tools.deploy_v2 --service finance_report/app --type staging --version-ref vX.Y.Z --iac-ref vX.Y.Z --domain zitian.party
```

### DB Connection Failed

**Symptoms**: `psycopg2.OperationalError`

**Fix**:
```bash
invoke fr-postgres.status
# Verify DATABASE_URL container name matches environment
# Re-run the relevant deploy_v2 workflow/command after fixing config.
```

### Secret Not Syncing

**Symptoms**: Old value persists

**Fix**:
```bash
invoke env.get <KEY> finance_report app production
# Re-run the relevant deploy_v2 workflow/command so the service consumes the secret.
```

---

## SOPs

### Deploy New Service

```bash
# 1. Secrets
invoke env.set DATABASE_URL "postgresql://..." myapp api production

# 2. Dependencies
cd repo && python -m tools.deploy_v2 --service platform/postgres --type staging --iac-ref vX.Y.Z --domain zitian.party
cd repo && python -m tools.deploy_v2 --service platform/redis --type staging --iac-ref vX.Y.Z --domain zitian.party

# 3. Register the service in IaC/service_registry, then deploy through deploy_v2.
cd repo && python -m tools.deploy_v2 --service myapp/api --type staging --iac-ref vX.Y.Z --domain zitian.party

# 4. Verify
python tools/debug.py logs myapp --tail 50
curl https://myapp.zitian.party/health
```

### Modify Config

```bash
invoke env.set DEBUG false finance_report app production
cd repo && python -m tools.deploy_v2 --service finance_report/app --type prod --version-ref vX.Y.Z --iac-ref vX.Y.Z --domain zitian.party --staging-validated --code-reviewed
curl https://report.zitian.party/health
```

### Rotate Secrets

```bash
NEW_PASSWORD=$(openssl rand -base64 32)
invoke env.set DB_PASSWORD "$NEW_PASSWORD" finance_report app production
docker exec finance_report-postgres psql -U postgres -c "ALTER USER myuser PASSWORD '$NEW_PASSWORD';"
invoke env.set DATABASE_URL "postgresql://myuser:$NEW_PASSWORD@finance_report-postgres:5432/finance_report" finance_report app production
cd repo && python -m tools.deploy_v2 --service finance_report/app --type prod --version-ref vX.Y.Z --iac-ref vX.Y.Z --domain zitian.party --staging-validated --code-reviewed
```

---

## Emergency Procedures

### System Down

```bash
ssh root@$VPS_HOST "uptime"
ssh root@$VPS_HOST "docker ps"
ssh root@$VPS_HOST "systemctl restart docker"  # If needed
# Re-run the relevant deploy_v2 workflow/command after the host is stable.
```

### Database Corruption

```bash
# Backup
docker exec finance_report-postgres pg_dumpall > /tmp/backup.sql
scp root@$VPS_HOST:/tmp/backup.sql ./

# Restore
docker exec -i finance_report-postgres psql -U postgres < backup.sql
# Re-run the relevant deploy_v2 workflow/command after restore validation.
```

### Vault Sealed

```bash
# Get keys from 1Password (bootstrap/vault)
ssh root@$VPS_HOST
docker exec -it vault vault operator unseal <KEY>  # Repeat 3x
# Re-run the relevant deploy_v2 workflow/command after Vault is healthy.
```

---

## Observability

### SigNoz

- Staging: `https://signoz-staging.zitian.party`
- Production: `https://signoz.zitian.party`
- Query: `service_name = "finance-report-backend"`

### Health Checks

```bash
curl https://report.zitian.party/health
invoke fr-app.status
```

---

## Multi-Environment

### Environment Variables

```bash
# Production (default)
export DEPLOY_ENV=production
→ Container: finance-report-backend
→ Path: /data/finance-report

# Staging
export DEPLOY_ENV=staging
→ Container: finance-report-backend-staging
→ Path: /data/finance-report-staging

# PR
export DEPLOY_ENV=pr-47
→ Container: finance-report-backend-pr-47
→ Path: /data/finance-report-pr-47
```

### Dokploy Network

**Critical**: Use unique container names.

❌ Wrong: `container_name: postgres`
✅ Right: `container_name: finance-report-db-pr-47`

---

## Security Best Practices

**DO**:
- Use `invoke` for operations
- Read-only SSH for investigation
- Rotate secrets every 90 days
- Verify health after changes
- Use environment-specific container names

**DON'T**:
- Modify files on VPS (deploy via CI)
- Use browser for production ops
- Hardcode secrets
- Use generic container names
- Skip health checks

---

## Quick Reference

```bash
# Debug
python tools/debug.py logs backend --env production
python tools/debug.py status backend --env production

# Secrets
invoke env.get DATABASE_URL finance_report app production
invoke env.set DEBUG false finance_report app production
invoke env.list-all finance_report app production

# Deploy
cd repo && python -m tools.deploy_v2 --service finance_report/app --type staging --version-ref vX.Y.Z --iac-ref vX.Y.Z --domain zitian.party
cd repo && python -m tools.deploy_v2 --service platform/redis --type staging --iac-ref vX.Y.Z --domain zitian.party

# Health
invoke fr-app.status
curl https://report.zitian.party/health
```

---

## Related Docs

- [AGENTS.md](../../../AGENTS.md) — Behavioral guidelines
- [development.md](../../../docs/ssot/development.md) — Dev workflows
- [observability.md](../../../docs/ssot/observability.md) — Logging
- [secrets-management](../secrets-management/SKILL.md) — Env vars
