---
name: production-debug
description: Debug production and staging environments using Dokploy API, VPS SSH, and SigNoz logs. Use when investigating deployment issues, checking service health, viewing logs, or troubleshooting real environment problems.
---

# Production/Staging Debug

> **Purpose**: Unified debugging workflow for production/staging via Dokploy API, SSH, and SigNoz.

## Quick Start

```bash
# Check service health
python scripts/debug.py status backend --env production

# View logs
python scripts/debug.py logs backend --tail 50 --follow

# List containers
python scripts/debug.py containers --env production

# Use SigNoz (production/staging)
python scripts/debug.py logs backend --env production --method signoz
```

---

## Container Naming Patterns

| Environment | Backend | Frontend |
|-------------|---------|----------|
| **Local/CI** | `finance-report-backend` | `finance-report-frontend` |
| **Staging** | `finance-report-backend-staging` | `finance-report-frontend-staging` |
| **Production** | `finance-report-backend` | `finance-report-frontend` |
| **PR (#47)** | `finance-report-backend-pr-47` | `finance-report-frontend-pr-47` |

---

## Common Operations

### View Logs

```bash
# Auto-detects environment
python scripts/debug.py logs backend
python scripts/debug.py logs frontend --env staging --follow

# Force SigNoz (historical logs)
python scripts/debug.py logs backend --env production --method signoz
```

### Check Service Health

```bash
python scripts/debug.py status backend --env production
python scripts/debug.py status frontend --env staging
```

### List Services

```bash
# List all finance-report containers
python scripts/debug.py containers --env production

# List all Dokploy projects/environments (Python)
python scripts/list_dokploy.py
```

---

## Dokploy API Operations

### View Service Configuration

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"  # Finance Report Production

compose = client.get_compose(compose_id)
print(f"Service: {compose.get('name')}")
print(f"Env vars:\n{compose.get('env')}")
```

### Update Environment Variables

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"

# Update specific vars (merges with existing)
client.update_compose_env(compose_id, env_vars={"DEBUG": "true"})

# Trigger redeploy
client.deploy_compose(compose_id)
```

**IMPORTANT**: Env var changes require infrastructure PR in `repo/` submodule.

### Trigger Deployment

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"

# Trigger redeploy
client.deploy_compose(compose_id)
```

---

## SSH Access (Emergency Only)

**IMPORTANT**: Prefer `scripts/debug.py` and Dokploy API. Deploy via CI, not manual SSH edits.

```bash
# SSH into VPS (read-only inspection)
ssh root@$VPS_HOST

# View logs
docker logs finance-report-backend --tail 50 -f

# Check container status
docker ps --filter name=finance-report

# Restart container (emergency only)
docker restart finance-report-backend
```

**Never via SSH**:
- ❌ Modify config files
- ❌ Manual database changes
- ❌ Install packages

---

## Troubleshooting

### Container Not Found

```bash
# List all containers
python scripts/debug.py containers --env production

# Verify naming pattern matches SSOT table above
```

### SSH Connection Failed

```bash
# Check environment
echo $VPS_HOST

# Test connection
ssh root@$VPS_HOST "echo Success"

# Load direnv if needed
direnv allow
```

### Logs Empty/Truncated

```bash
# Check container uptime
docker ps --filter name=finance-report-backend --format "{{.Status}}"

# Use SigNoz for historical logs
python scripts/debug.py logs backend --env production --method signoz
```

### Deployment Stuck

```python
# Check deployment history via Python
from libs.dokploy import get_dokploy
client = get_dokploy()
deployments = client._request('GET', 'compose.deployments?composeId=A6V-hbJlgHMwgPDoTDnhH')
for dep in deployments[:5]:
    print(f"ID: {dep['deploymentId']}, Status: {dep['status']}")
```

Or use utility script:
```bash
python scripts/check_deployments.py
```

---

## Safety Guidelines

**Read-Only First**:
- ✅ View logs, check status, list containers
- ✅ Read env vars via Dokploy API

**Deployment Changes**:
1. Make changes in code
2. Open PR → Deploy via GitHub Actions
3. Emergency only: Use Dokploy API → Document in PR

---

## SigNoz Integration

For production/staging structured logs:

- **Staging**: `https://signoz-staging.zitian.party`
- **Production**: `https://signoz.zitian.party`

Query by service name:
```
service_name = "finance-report-backend"
```

See [docs/ssot/observability.md](../../../docs/ssot/observability.md) for OTLP configuration.

---

## Verification

After debugging:

```bash
# 1. Check health
python scripts/debug.py status backend --env production

# 2. Test endpoint
curl https://report.zitian.party/api/health

# 3. Run smoke tests
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh
```

---

## Related Documentation

- [Development SSOT](../../../docs/ssot/development.md) — Deployment architecture
- [Observability SSOT](../../../docs/ssot/observability.md) — Logging and SigNoz
- [Dokploy API Client](../../../repo/libs/dokploy.py) — API source code

---

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_dokploy.py` | View service configuration |
| `scripts/list_dokploy.py` | List all projects/environments/services |
| `scripts/check_deployments.py` | Check deployment history |
| `scripts/check_compose_details.py` | Inspect compose details (JSON dump) |
