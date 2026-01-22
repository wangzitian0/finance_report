---
name: production-debug
description: Debug production and staging environments using Dokploy API, VPS SSH, and SigNoz logs. Use when investigating deployment issues, checking service health, viewing logs, or troubleshooting real environment problems.
---

# Production/Staging Debug

> Unified debugging for production/staging via Dokploy API, SSH, and SigNoz.

## Quick Reference

```bash
# View logs
python scripts/debug.py logs backend --tail 50 --follow
python scripts/debug.py logs backend --env staging

# Check health
python scripts/debug.py status backend --env production

# List containers
python scripts/debug.py containers --env production

# SigNoz (historical logs)
python scripts/debug.py logs backend --env production --method signoz
```

---

## Container Naming

| Environment | Pattern |
|-------------|---------|
| Local/CI | `finance-report-{service}` |
| Staging | `finance-report-{service}-staging` |
| Production | `finance-report-{service}` |
| PR #47 | `finance-report-{service}-pr-47` |

---

## Dokploy API

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"  # Finance Report

# View config
compose = client.get_compose(compose_id)
print(compose.get('env'))

# Update env vars
client.update_compose_env(compose_id, env_vars={"DEBUG": "true"})

# Trigger deploy
client.deploy_compose(compose_id)
```

**Note**: Env var changes need PR in `repo/` submodule.

---

## SSH (Emergency Only)

```bash
ssh root@$VPS_HOST

# View logs
docker logs finance-report-backend -f --tail 50

# Restart (emergency)
docker restart finance-report-backend
```

**Never**: Modify files, manual DB changes, install packages via SSH.

---

## Troubleshooting

**Container not found**: `python scripts/debug.py containers --env production`

**SSH fails**: Check `$VPS_HOST`, test with `ssh root@$VPS_HOST "echo OK"`

**Empty logs**: Use SigNoz for historical logs

**Deployment stuck**: `python scripts/check_deployments.py`

---

## Utility Scripts

- `scripts/check_dokploy.py` - View service config
- `scripts/list_dokploy.py` - List all resources
- `scripts/check_deployments.py` - Deployment history
- `scripts/check_compose_details.py` - Full compose JSON

---

## SigNoz

- Staging: `https://signoz-staging.zitian.party`
- Production: `https://signoz.zitian.party`
- Query: `service_name = "finance-report-backend"`

---

## Docs

- [Development SSOT](../../../docs/ssot/development.md)
- [Observability SSOT](../../../docs/ssot/observability.md)
- [Dokploy API](../../../repo/libs/dokploy.py)
