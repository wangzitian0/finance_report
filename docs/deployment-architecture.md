# Deployment Architecture Guide

## Overview

Finance Report uses a three-layer environment model, from local development to production, with clear separation of responsibilities.

## Environment Layers

### Layer 1️⃣: Local Development & Local CI

**Goal**: Fast feedback with minimal environment dependencies.

| Aspect | Description |
|--------|-------------|
| **Tools** | moon, pytest, eslint (CLI-only, no Docker) |
| **Commands** | `moon run backend:lint`, `pytest` |
| **Traits** | Sub-second feedback, mock/local providers |
| **Scope** | Code validation, unit tests, type checks |

**No Docker involved — fastest dev loop.**

### Layer 2️⃣: GitHub CI & PR Tests

**Trigger**: `git push` → PR created or updated on `main`

| Aspect | Description |
|--------|-------------|
| **Compose** | `docker-compose.yml` (this repo) |
| **Platform** | GitHub Actions (CI) + Dokploy (PR test) |
| **Build** | Build from source (no image registry) |
| **Services** | PostgreSQL, Redis, MinIO, Backend, Frontend |
| **Data** | Ephemeral (cleaned by GitHub Actions) |
| **Use** | Integration tests, PR validation |
| **URL** | GitHub CI only (no external URL) |

- Run lint, backend tests, frontend build
- Start `docker-compose.yml` for integration tests
- Output coverage report

- PR creates a full environment automatically
- Domain: `report-pr-{number}.zitian.party`
- PR close auto-destroys the environment

**Fast validation without Docker image overhead.**

### Layer 3️⃣: Staging & Production (Shared Infrastructure)

**Shared traits**:
- Compose: parameterized templates from the `infra2` repository
- Images: GHCR registry
- Secrets: Vault (production-grade security)
- Platform: Dokploy (orchestration)

#### Staging

**Trigger**: Auto-deploy on `main` push (auto-increment patch version)

| Aspect | Description |
|--------|-------------|
| **Platform** | Dokploy (Projects > finance_report > staging) |
| **Domain** | `report-staging.zitian.party` |
| **Image tag** | Auto patch version (e.g., `v1.0.45`) |
| **Data** | **Persistent** (volumes retained) |
| **Env vars** | `ENV=staging` |
| **Lifecycle** | Long-running (weeks/months) |
| **Use** | E2E tests, smoke tests, ongoing validation |

Release flow:
1. Compute next patch version (v1.0.x → v1.0.x+1)
2. Build backend/frontend images
3. Push to GHCR (tag: v1.0.45)
4. Call Dokploy API to update Staging
5. Update `IMAGE_TAG=v1.0.45`

#### Production

**Trigger**: Manual promote or release tag

| Aspect | Description |
|--------|-------------|
| **Platform** | Dokploy (Projects > finance_report > production) |
| **Domain** | `report.zitian.party` |
| **Image tag** | Specific release (e.g., `v1.0.45` or `v1.1.0`) |
| **Data** | Critical business data |
| **Env vars** | `ENV=production` |
| **Lifecycle** | Stable |
| **Deploy strategy** | Blue-green or rolling update |

Release flow:
1. Manual trigger or release tag
2. Select target version (e.g., v1.0.45 from Staging)
3. Verify image exists
4. Call Dokploy API to update Production
5. Update `IMAGE_TAG=v1.0.45`

## Six-Layer Environment Progression

Each environment is closer to production but trades speed for realism.

| Environment | Production Fidelity | Feedback Speed | Key Differences |
|-------------|---------------------|----------------|-----------------|
| **1. Local Dev** | ⭐ | 🚀🚀🚀 | No Docker, mock data, hot reload |
| **2. Local Integration** | ⭐⭐ | 🚀🚀 | Local Docker, real DB, no network latency |
| **3. GitHub CI** | ⭐⭐⭐ | 🚀 | Ephemeral, clean state, automated tests |
| **4. PR Test** | ⭐⭐⭐⭐ | 🐢 | Isolated cloud env, source build, preview |
| **5. Staging** | ⭐⭐⭐⭐⭐ | 🐢🐢 | Real infra config, persistent data, auto patch version |
| **6. Production** | ⭐⭐⭐⭐⭐⭐ | 🐢🐢🐢 | Real traffic, manually controlled versions |

## File Inventory

### Compose Files

| File | Purpose | Environment |
|------|---------|------------|
| **`docker-compose.yml`** | Unified dev/CI/PR compose | local / GitHub CI / PR test |
| **`repo/finance_report/.../compose.yaml`** | Staging & Production template | staging / production |

> The project maintains two compose files and uses env vars to control behavior.

### Workflow Files

| File | Trigger | Purpose |
|------|---------|---------|
| **`ci.yml`** | PR open/update + main push | Code validation + integration tests |
| **`pr-test.yml`** | PR open/sync/close | PR test environment (auto create/destroy) |
| **`staging-deploy.yml`** | main push | Build images + deploy staging |
| **`production-deploy.yml`** | release tag | Build images + deploy production |

### Configuration

#### Vault Structure

```
secret/
  finance_report/
    staging/
      ...
    production/
      ...
```

| Secret | Purpose |
|--------|---------|
| `DOKPLOY_API_KEY` | Dokploy API auth |
| `DOKPLOY_GITHUB_ID` | GitHub integration ID (`126refcRlCoWj6pmPXElU`) |

## Example Development Workflow

### Shipping a Feature

1. Create a feature branch
2. Local dev + local CI validation (fast feedback)
3. If full env is needed, start Docker Compose
4. Commit and push
5. Open a PR
6. GitHub CI validates tests automatically
7. Dokploy creates PR test environment
8. Use `report-pr-{number}.zitian.party` for testing
9. Each push updates the PR test env
10. PR close destroys the env

### Promote to Staging

1. Merge to `main`
2. GitHub CI validates
3. Auto-deploy to staging
4. `staging-deploy.yml` builds images (tag: `sha-xxx`)
5. Deploy to `report-staging.zitian.party`
6. QA / smoke tests on persistent data

### Promote to Production

1. Create a release tag
2. GitHub Actions triggers `production-deploy.yml`
3. Build images (tag: `v1.2.3`)
4. Deploy to `report.zitian.party`
5. Run smoke tests
6. Monitor production

## Architecture Advantages

| Advantage | Description |
|-----------|-------------|
| **Fast feedback** | CLI-based tests run quickly in local dev |
| **Cost control** | Images are only built/pushed in staging/production workflows |
| **Isolation** | PRs get isolated full environments |
| **Durable data** | Staging keeps data for ongoing validation |
| **Version clarity** | Production uses semantic versions |
| **Recovery ready** | Staging mirrors production configuration |

## Technical Details

### Role of `docker-compose.yml`

1. **Local dev**: `docker compose up -d` starts full environment
2. **GitHub CI**: auto-start for integration tests
3. **PR Test**: Dokploy reads and deploys from GitHub repo

### Role of `infra2` compose.yaml

1. Shared template for Staging/Production
2. Env vars distinguish `ENV=staging` vs `ENV=production`
3. Vault agent injects secrets
4. Traefik labels handle routing and SSL

### Image Tag Strategy

| Environment | Tag | Notes |
|-------------|-----|-------|
| PR test | N/A | Docker compose build (no registry) |
| Staging | `sha-{commit_hash}` | Track latest `main` |
| Production | `v1.2.3` | Semantic versions for stability |

## Open Items

### Configuration
- [x] Update README to document how to start `docker-compose.yml`
- [ ] Configure GitHub repo environment protection rules (optional)

### Testing
- [x] Local `docker compose up -d` verification
- [x] GitHub CI verification
- [x] Test PR end-to-end validation
- [x] Staging deployment validation
- [x] Production deployment validation
