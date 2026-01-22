---
name: production-debug
description: Debug production and staging environments using Dokploy API, VPS SSH, and SigNoz logs. Use when investigating deployment issues, checking service health, viewing logs, or troubleshooting real environment problems.
---

# Production/Staging Debug

> **Purpose**: Unified debugging workflow for production and staging environments via Dokploy API, SSH, and SigNoz.

## When to Use This Skill

Use this skill when:
- Investigating deployment failures or health check errors
- Viewing production/staging logs without SSH
- Checking service status or container states
- Debugging environment variable issues
- Triggering manual redeployments
- Analyzing application behavior in real environments

**DO NOT use for**:
- Local development issues → Use `domain/development` skill
- Database schema changes → Use `domain/schema` skill
- Testing → Use `professional/qa-testing` skill

---

## Quick Start

```bash
# 1. Check service health (uses Dokploy API)
python scripts/debug.py status backend --env production

# 2. View logs (auto-detects: Docker vs SSH+SigNoz)
python scripts/debug.py logs backend --tail 50

# 3. View staging logs
python scripts/debug.py logs frontend --env staging --follow

# 4. List all containers in an environment
python scripts/debug.py containers --env production
```

---

## Architecture Overview

### Environment Detection

The debug tool automatically detects your environment:

| Environment | Method | Log Source |
|-------------|--------|------------|
| **Local/CI** | Docker API | `docker logs` (direct) |
| **Staging** | SSH + Dokploy | `ssh + docker logs` or SigNoz |
| **Production** | SSH + Dokploy | `ssh + docker logs` or SigNoz |

### Container Naming Patterns

| Environment | Backend | Frontend | Postgres | Redis |
|-------------|---------|----------|----------|-------|
| **Local/CI** | `finance-report-backend` | `finance-report-frontend` | `finance-report-db` | `finance-report-redis` |
| **Staging** | `finance-report-backend-staging` | `finance-report-frontend-staging` | `finance-report-db-staging` | `finance-report-redis-staging` |
| **Production** | `finance-report-backend` | `finance-report-frontend` | `finance-report-db` | `finance-report-redis` |
| **PR (#47)** | `finance-report-backend-pr-47` | `finance-report-frontend-pr-47` | `finance-report-db-pr-47` | `finance-report-redis-pr-47` |

---

## Instructions

### Step 1: Environment Setup

Ensure you have the required credentials:

```bash
# Check environment variables
python scripts/debug.py --help

# Required variables (from 1Password or direnv):
# - VPS_HOST: Production server hostname
# - INTERNAL_DOMAIN: Base domain (e.g., zitian.party)
# - DOKPLOY_API_KEY: Dokploy API key (optional, for Dokploy operations)
```

### Step 2: Common Operations

#### 2.1 Check Service Health

```bash
# View last 20 lines of logs (quick health check)
python scripts/debug.py status backend --env production
python scripts/debug.py status frontend --env staging

# This internally calls: docker logs <container> --tail 20
```

#### 2.2 View Logs

```bash
# Tail logs (default: 100 lines)
python scripts/debug.py logs backend
python scripts/debug.py logs frontend --tail 200

# Follow logs in real-time
python scripts/debug.py logs backend --follow

# Specify environment
python scripts/debug.py logs backend --env staging
```

#### 2.3 List Containers

```bash
# List all finance-report containers in an environment
python scripts/debug.py containers --env production
python scripts/debug.py containers --env staging
```

#### 2.4 Use SigNoz (Production/Staging Only)

For structured logs shipped via OTLP:

```bash
# Force SigNoz method (instead of Docker logs)
python scripts/debug.py logs backend --env production --method signoz

# SigNoz URLs:
# - Staging: https://signoz-staging.zitian.party
# - Production: https://signoz.zitian.party
```

Query logs by service name in SigNoz:
```
service_name = "finance-report-backend"
```

See [docs/ssot/observability.md](../../../docs/ssot/observability.md) for OTLP configuration.

---

## Advanced Operations

### Using Dokploy API Directly

When `scripts/debug.py` is insufficient, use the Dokploy client from `repo/libs/dokploy.py`:

#### Check Service Configuration

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"  # Finance Report Production

# Get service details
compose = client.get_compose(compose_id)
print(f"Service Name: {compose.get('name')}")
print(f"Environment Variables:\n{compose.get('env')}")
```

#### List All Projects/Environments/Services

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
projects = client.list_projects()

for project in projects:
    print(f"Project: {project.get('name')}")
    for env in project.get('environments', []):
        print(f"  Environment: {env.get('name')}")
        for compose in env.get('compose', []):
            print(f"    Compose: {compose.get('name')} ({compose.get('composeId')})")
```

#### Trigger Manual Redeploy

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"

# Update compose file (switch to raw mode)
with open("scripts/compose_temp.yaml", "r") as f:
    compose_content = f.read()

client.update_compose(compose_id, compose_file=compose_content, sourceType="raw")

# Trigger deployment
client.deploy_compose(compose_id)
print("Deployment triggered.")
```

---

### SSH Direct Access (Last Resort)

**IMPORTANT**: Prefer `scripts/debug.py` over direct SSH. Direct modifications on VPS are discouraged—deploy via CI instead.

```bash
# SSH into VPS (read-only inspection recommended)
ssh root@$VPS_HOST

# Check container status
docker ps --filter name=finance-report

# View logs directly
docker logs finance-report-backend --tail 50
docker logs finance-report-backend -f

# Restart container (use with caution)
docker restart finance-report-backend
```

**When to use SSH**:
- Emergency production debugging
- Operations not covered by `debug.py`
- Inspecting file system or network state

**Never via SSH**:
- Modifying code/config files
- Manual database changes
- Installing packages

---

## Troubleshooting Guide

### Issue: "Container not found"

**Cause**: Wrong environment or container naming mismatch.

**Solution**:
```bash
# List all containers in environment
python scripts/debug.py containers --env production

# Verify container name pattern matches SSOT
# See "Container Naming Patterns" table above
```

### Issue: "SSH connection failed"

**Cause**: `VPS_HOST` not set or SSH key missing.

**Solution**:
```bash
# Check environment
echo $VPS_HOST

# Test SSH connection
ssh root@$VPS_HOST "echo Connection successful"

# If using direnv, ensure .envrc is loaded
direnv allow
```

### Issue: "Logs are empty or truncated"

**Cause**: Container recently restarted or logs rotated.

**Solution**:
```bash
# Check container uptime
docker ps --filter name=finance-report-backend --format "{{.Status}}"

# Use SigNoz for historical logs
python scripts/debug.py logs backend --env production --method signoz
```

### Issue: "Deployment stuck in 'building' state"

**Cause**: CI/CD pipeline failure or Dokploy queue backlog.

**Solution**:
```bash
# Check deployment history
python -c "
from libs.dokploy import get_dokploy
client = get_dokploy()
deployments = client._request('GET', 'compose.deployments?composeId=A6V-hbJlgHMwgPDoTDnhH')
for dep in deployments[:5]:
    print(f\"ID: {dep.get('deploymentId')}, Status: {dep.get('status')}, Created: {dep.get('createdAt')}\")
"
```

---

## Safety Guidelines

### Read-Only First

**DO**:
- ✅ View logs (`debug.py logs`)
- ✅ Check service status (`debug.py status`)
- ✅ List containers (`debug.py containers`)
- ✅ Read environment variables via Dokploy API

**DON'T**:
- ❌ Modify config files on VPS
- ❌ Restart containers manually (unless emergency)
- ❌ Run `docker exec` to change state
- ❌ Edit environment variables via SSH

### Deployment Changes

**Preferred Flow**:
1. Make changes in code
2. Commit to branch
3. Open PR
4. Deploy via GitHub Actions

**Emergency Only**:
- Use Dokploy API to update env vars
- Trigger redeploy via `client.deploy_compose()`
- Document changes in PR afterwards

---

## Environment Variable Debugging

### Viewing Environment Variables

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"

# Get current env vars
env_str = client.get_compose_env(compose_id)
print(env_str)
```

### Updating Environment Variables

```python
from libs.dokploy import get_dokploy

client = get_dokploy()
compose_id = "A6V-hbJlgHMwgPDoTDnhH"

# Update specific env vars (merges with existing)
client.update_compose_env(compose_id, env_vars={
    "DEBUG": "true",
    "LOG_LEVEL": "debug"
})

# Or replace entirely
new_env = """
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
DEBUG=false
"""
client.update_compose_env(compose_id, env_str=new_env)

# Trigger redeploy for changes to take effect
client.deploy_compose(compose_id)
```

**IMPORTANT**: Environment variable changes require infrastructure PR in `repo/` submodule (infra2). See [docs/ssot/development.md](../../../docs/ssot/development.md#cross-repo-synchronization).

---

## Related Documentation

- **[Development SSOT](../../../docs/ssot/development.md)** — Development workflow and deployment architecture
- **[Observability SSOT](../../../docs/ssot/observability.md)** — Logging and SigNoz configuration
- **[Infra2 README](../../../repo/README.md)** — Infrastructure automation and environment management
- **[Dokploy API Client](../../../repo/libs/dokploy.py)** — Source code for Dokploy client

---

## Verification

After debugging, verify the fix worked:

```bash
# 1. Check service health
python scripts/debug.py status backend --env production

# 2. Verify specific endpoint
curl https://report.zitian.party/api/health

# 3. Run smoke tests
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh
```

---

## Key Takeaways

1. **Use `scripts/debug.py` as primary tool** — Handles environment detection automatically
2. **Prefer Dokploy API over SSH** — Safer and auditable
3. **Read-only first, modify via CI** — Avoid manual production changes
4. **SigNoz for historical logs** — Docker logs are ephemeral
5. **Document emergency changes** — Create PR after manual fixes
