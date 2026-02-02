# Dokploy Deployment Configuration Guide

## Problem: Traefik 404 Errors on Staging/Production

The staging and production deployments were failing with HTTP 404 errors because **Docker Compose label substitution** for Traefik routing was not working correctly. Environment variables set via the Dokploy API were not being applied when docker-compose created containers.

## Root Cause

Docker Compose reads labels at **container creation time** and performs variable substitution **when parsing the compose file**. Environment variables must be available in the shell environment when `docker-compose up` runs, not just stored in Dokploy's database.

The original `docker-compose.yml` used variable substitution:
```yaml
labels:
  - "traefik.http.routers.finance-report-api${ENV_SUFFIX:-}.rule=Host(`report${ENV_DOMAIN_SUFFIX:-}.${INTERNAL_DOMAIN:-zitian.party}`) && PathPrefix(`/api`)"
```

This requires `ENV_SUFFIX`, `ENV_DOMAIN_SUFFIX`, and `INTERNAL_DOMAIN` to be set when compose runs, but Dokploy's API environment variables weren't being passed to the docker-compose execution environment.

## Solution: Environment-Specific Compose Override Files

We've created separate compose override files with **hardcoded** Traefik labels (no variable substitution):

- `docker-compose.staging.yml` - Staging-specific configuration
- `docker-compose.production.yml` - Production-specific configuration

These files **extend** the base `docker-compose.yml` and override:
1. Traefik labels with hardcoded values
2. Container names with environment suffixes
3. Network names for isolation
4. Environment variables (NEXT_PUBLIC_APP_URL, ENVIRONMENT, etc.)

## Dokploy Configuration Steps

### For Staging Environment

1. Go to Dokploy dashboard → Your staging compose project
2. Navigate to **Settings** → **Compose Configuration**
3. Update the **Compose File Path** or **Additional Compose Files** field to:
   ```
   docker-compose.yml:docker-compose.staging.yml
   ```
   OR if Dokploy supports it:
   ```
   -f docker-compose.yml -f docker-compose.staging.yml
   ```

4. Ensure the following environment variables are set in Dokploy UI (for secrets and dynamic values):
   ```env
   IMAGE_TAG=<set by CI/CD>
   GIT_COMMIT_SHA=<set by CI/CD>
   COMPOSE_PROFILES=app
   
   # Secrets (set manually in Dokploy UI)
   DATABASE_URL=postgresql+asyncpg://...
   SECRET_KEY=<secure random value>
   REDIS_URL=redis://...
   OPENROUTER_API_KEY=sk-or-v1-...
   S3_ENDPOINT=http://...
   S3_ACCESS_KEY=...
   S3_SECRET_KEY=...
   ```

5. **Redeploy** the staging compose project

### For Production Environment

Follow the same steps as staging, but use:
```
docker-compose.yml:docker-compose.production.yml
```

## Alternative: Symlink Approach (If Dokploy Doesn't Support Multiple Files)

If Dokploy doesn't support specifying multiple compose files, create environment-specific symlinks:

### Staging Repository Setup
In your Dokploy staging deployment, add a `.dokploy/deploy.sh` script:
```bash
#!/bin/bash
set -e

# Create symlink for staging override
ln -sf docker-compose.staging.yml docker-compose.override.yml

# Docker Compose automatically reads docker-compose.override.yml
docker-compose up -d
```

### Production Repository Setup
Same as staging, but:
```bash
ln -sf docker-compose.production.yml docker-compose.override.yml
```

Docker Compose automatically merges `docker-compose.yml` with `docker-compose.override.yml` if both exist.

## Verification

After configuration, verify the deployment:

### Check Container Labels
```bash
docker inspect finance-report-backend-staging | jq '.[0].Config.Labels' | grep traefik
```

Expected output for staging:
```json
{
  "traefik.enable": "true",
  "traefik.http.routers.finance-report-api-staging.rule": "Host(`report-staging.zitian.party`) && PathPrefix(`/api`)",
  ...
}
```

### Test Health Endpoint
```bash
curl -I https://report-staging.zitian.party/api/health
```

Expected output:
```
HTTP/2 200
content-type: application/json
```

### Check Traefik Dashboard
Visit Traefik dashboard (if available) and verify:
- Router `finance-report-api-staging` exists
- Service `finance-report-api-staging` is UP
- Rule matches `Host(report-staging.zitian.party) && PathPrefix(/api)`

## Files Created

1. `.env.staging` - Staging environment variables (for reference, may not be used if hardcoded in override)
2. `.env.production` - Production environment variables (for reference)
3. `docker-compose.staging.yml` - Staging compose override with hardcoded labels
4. `docker-compose.production.yml` - Production compose override with hardcoded labels

## Why This Works

✅ **No variable substitution needed** - Traefik labels are hardcoded in override files  
✅ **No API environment variable issues** - Labels are baked into the compose file  
✅ **Clear separation** - Each environment has explicit configuration  
✅ **Easy debugging** - No guessing what variables expand to  
✅ **Git-tracked** - All configuration is version controlled  

## Next Steps

1. Configure Dokploy to use the override files (see above)
2. Trigger a new deployment
3. Verify health endpoint returns 200
4. If successful, apply same configuration to production

## Rollback Plan

If the new configuration fails, revert Dokploy to use only `docker-compose.yml` and manually set environment variables via Dokploy UI:
```env
TRAEFIK_ENABLE=true
ENV_SUFFIX=-staging
ENV_DOMAIN_SUFFIX=-staging
INTERNAL_DOMAIN=zitian.party
```

Then investigate why the override files aren't being loaded.
