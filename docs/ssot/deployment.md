# Deployment (Source of Truth)

> **SSOT Key**: `deployment`
> **Core Definition**: Environment layers, compose files, CI/CD workflows, and deployment strategy.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Local/CI Compose** | `docker-compose.yml` | Dev, GitHub CI, PR test environments |
| **Staging/Prod Compose** | `repo/finance_report/.../compose.yaml` | Staging & Production templates |
| **CI Workflows** | `.github/workflows/*.yml` | GitHub Actions definitions |
| **Vault Secrets** | `secret/finance_report/{staging,production}` | Environment-specific secrets |

---

## 2. Architecture Model

### Six-Layer Environment Progression

Each layer trades feedback speed for production fidelity.

| Layer | Environment | Fidelity | Speed | Key Characteristics |
|-------|-------------|----------|-------|---------------------|
| 1 | **Local Dev** | ⭐ | 🚀🚀🚀 | No Docker, mock data, hot reload |
| 2 | **Local Integration** | ⭐⭐ | 🚀🚀 | Local Docker, real DB, no network latency |
| 3 | **GitHub CI** | ⭐⭐⭐ | 🚀 | Ephemeral, clean state, automated tests |
| 4 | **PR Test** | ⭐⭐⭐⭐ | 🐢 | Isolated cloud env, source build, preview |
| 5 | **Staging** | ⭐⭐⭐⭐⭐ | 🐢🐢 | Real infra, persistent data, auto patch version |
| 6 | **Production** | ⭐⭐⭐⭐⭐⭐ | 🐢🐢🐢 | Real traffic, manually controlled versions |

### Layer 1️⃣: Local Development

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
| **URL** | PR: `report-pr-{number}.zitian.party` |

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

#### Production

**Trigger**: Manual promote or release tag

| Aspect | Description |
|--------|-------------|
| **Platform** | Dokploy (Projects > finance_report > production) |
| **Domain** | `report.zitian.party` |
| **Image tag** | Specific release (e.g., `v1.0.45` or `v1.1.0`) |
| **Data** | Critical business data |
| **Env vars** | `ENV=production` |
| **Deploy strategy** | Blue-green or rolling update |

---

## 3. Design Constraints

### ✅ Recommended Patterns

| Pattern | Description |
|---------|-------------|
| **A. Layer progression** | Always validate at lower layers before higher |
| **B. Semantic versioning** | Production uses explicit semantic versions |
| **C. Ephemeral PR environments** | PR close auto-destroys the environment |
| **D. Vault for secrets** | Never commit secrets to repo |

### ⛔ Prohibited Patterns

| Anti-pattern | Why |
|--------------|-----|
| **Skip CI to staging** | Untested code may break staging |
| **Direct production push** | Must go through staging validation |
| **Hardcode environment values** | Use env vars and Vault |
| **Generic container names** | Use unique names (e.g., `finance-report-db-pr-47`) to avoid routing conflicts |

---

## 4. Playbooks (SOP)

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
3. Auto-deploy to staging via `staging-deploy.yml`
4. Build images (tag: `sha-xxx` or auto patch version)
5. Deploy to `report-staging.zitian.party`
6. QA / smoke tests on persistent data

### Promote to Production

1. Create a release tag
2. GitHub Actions triggers `production-deploy.yml`
3. Build images (tag: `v1.2.3`)
4. Deploy to `report.zitian.party`
5. Run smoke tests
6. Monitor production

---

## 5. Verification (The Proof)

### File Inventory

#### Compose Files

| File | Purpose | Environment |
|------|---------|-------------|
| `docker-compose.yml` | Unified dev/CI/PR compose | local / GitHub CI / PR test |
| `repo/finance_report/.../compose.yaml` | Staging & Production template | staging / production |

#### Workflow Files

| File | Trigger | Purpose |
|------|---------|---------|
| `ci.yml` | PR open/update + main push | Code validation + integration tests |
| `pr-test.yml` | PR open/sync/close | PR test environment (auto create/destroy) |
| `staging-deploy.yml` | main push | Build images + deploy staging |
| `production-deploy.yml` | release tag | Build images + deploy production |

### Image Tag Strategy

| Environment | Tag | Notes |
|-------------|-----|-------|
| PR test | N/A | Docker compose build (no registry) |
| Staging | `sha-{commit_hash}` or `v1.0.x` | Track latest `main` |
| Production | `v1.2.3` | Semantic versions for stability |

### Vault Structure

```
secret/
  finance_report/
    staging/
      DATABASE_URL, S3_*, DOKPLOY_*, ...
    production/
      DATABASE_URL, S3_*, DOKPLOY_*, ...
```

### Verification Commands

```bash
# Verify local compose
docker compose config

# Verify CI workflows syntax
gh workflow list

# Check PR environment
curl -s https://report-pr-{number}.zitian.party/health

# Check staging
curl -s https://report-staging.zitian.party/health

# Check production
curl -s https://report.zitian.party/health
```

---

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

---

## Used by

- [development.md](./development.md)
- [observability.md](./observability.md)
