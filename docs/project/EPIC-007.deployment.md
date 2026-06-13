# EPIC-007: Production Deployment

> **Status**: ✅ Complete  
> **Vision Anchor**: `decision-7-tech-stack`  
> **Phase**: 0 (Infrastructure)  
> **Duration**: 1 week  
> **Dependencies**: EPIC-001, EPIC-002, EPIC-003  

---

## 🎯 Objective

Deploy Finance Report application to production environment using Dokploy + vault-init pattern, with independent PostgreSQL and Redis instances.

**Target Domain**: `report.${INTERNAL_DOMAIN}` (e.g., `report.zitian.party`)

**Core Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                      report.zitian.party                     │
│                    (Frontend + Backend)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ Traefik
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   finance_report Project                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  PostgreSQL │  │    Redis    │  │   App (BE + FE)     │  │
│  │   (01.pg)   │  │  (02.redis) │  │     (10.app)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   platform (Shared)                          │
│                   MinIO (03.minio)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Isolation | Independent PG/Redis, shared MinIO, vault-init for secrets |
| 💻 **Developer** | CI/CD | Docker build from apps/, compose orchestration |
| 🔒 **Security** | Secrets | Vault KV v2, no disk persistence, tmpfs for secrets |
| 🌐 **Network** | Domain | Single domain for FE+BE, Traefik routing |
| 📋 **PM** | Scope | Deploy EPIC 1-3 features first |

---

## ✅ Task Checklist

### Phase 1: Infrastructure Setup

- [x] Add infra2 as submodule at `repo/`
- [x] Create `repo/finance_report/finance_report/` directory structure
- [x] Create README.md for finance_report layer

### Phase 2: Database Layer (01.postgres)

- [x] `compose.yaml` - PostgreSQL 16 with vault-agent sidecar
- [x] `deploy.py` - PostgresDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for postgres
- [x] `secrets.ctmpl` - Secrets template
- [x] `README.md` - Documentation

### Phase 3: Cache Layer (02.redis)

- [x] `compose.yaml` - Redis with vault-agent sidecar
- [x] `deploy.py` - RedisDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for redis
- [x] `secrets.ctmpl` - Secrets template
- [x] `README.md` - Documentation

### Phase 4: Application Layer (10.app)

- [x] `compose.yaml` - Backend + Frontend with vault-agent sidecar
- [x] `deploy.py` - AppDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for app
- [x] `secrets.ctmpl` - Secrets template (DATABASE_URL, REDIS_URL, S3_*, ZAI_API_KEY)
- [x] `README.md` - Documentation
- [x] Traefik labels for `report.${INTERNAL_DOMAIN}`

### Phase 5: Vault Secrets Setup

- [x] Write secrets to Vault:
  ```
  secret/data/finance_report/<env>/postgres
    - POSTGRES_PASSWORD
  secret/data/finance_report/<env>/redis
    - PASSWORD
  secret/data/finance_report/<env>/app
    - DATABASE_URL
    - REDIS_URL
    - S3_ENDPOINT
    - S3_ACCESS_KEY
    - S3_SECRET_KEY
    - S3_BUCKET
    - ZAI_API_KEY
  ```
- [x] Generate service tokens via `invoke vault.setup-tokens`

### Phase 6: Deployment & Verification

- [x] Deploy postgres: `invoke finance_report.postgres.setup`
- [x] Deploy redis: `invoke finance_report.redis.setup`
- [x] Deploy app: `invoke finance_report.app.setup`
- [x] Verify health checks
- [x] Test `https://report.${INTERNAL_DOMAIN}`

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/infra/` and `tools/smoke_test.sh`

### AC7.1: Infrastructure Setup

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.1.1 | Infra2 submodule exists | Manual verification | Git | P0 |
| AC7.1.2 | Finance_report directory structure | Manual verification | `repo/finance_report/` | P0 |
| AC7.1.3 | README documentation exists | Manual verification | `repo/finance_report/finance_report/README.md` | P0 |

### AC7.2: Database Layer (PostgreSQL)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.2.1 | PostgreSQL container configured | Manual verification | `repo/finance_report/finance_report/01.postgres/compose.yaml` | P0 |
| AC7.2.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/01.postgres/compose.yaml` | P0 |
| AC7.2.3 | Vault policy for postgres | Manual verification | `repo/finance_report/finance_report/01.postgres/vault-policy.hcl` | P0 |
| AC7.2.4 | Secrets template for postgres | Manual verification | `repo/finance_report/finance_report/01.postgres/secrets.ctmpl` | P0 |
| AC7.2.5 | PostgresDeployer class exists | Manual verification | `repo/finance_report/finance_report/01.postgres/deploy.py` | P0 |

### AC7.3: Cache Layer (Redis)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.3.1 | Redis container configured | Manual verification | `repo/finance_report/finance_report/02.redis/compose.yaml` | P0 |
| AC7.3.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/02.redis/compose.yaml` | P0 |
| AC7.3.3 | Vault policy for redis | Manual verification | `repo/finance_report/finance_report/02.redis/vault-policy.hcl` | P0 |
| AC7.3.4 | Secrets template for redis | Manual verification | `repo/finance_report/finance_report/02.redis/secrets.ctmpl` | P0 |
| AC7.3.5 | RedisDeployer class exists | Manual verification | `repo/finance_report/finance_report/02.redis/deploy.py` | P0 |

### AC7.4: Application Layer (Backend + Frontend)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.4.1 | App container configured | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.3 | Vault policy for app | Manual verification | `repo/finance_report/finance_report/10.app/vault-policy.hcl` | P0 |
| AC7.4.4 | Secrets template for app | Manual verification | `repo/finance_report/finance_report/10.app/secrets.ctmpl` | P0 |
| AC7.4.5 | Traefik labels for domain | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.6 | AppDeployer class exists | Manual verification | `repo/finance_report/finance_report/10.app/deploy.py` | P0 |

### AC7.5: Vault Secrets Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.5.1 | DATABASE_URL in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.2 | REDIS_URL in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.3 | S3_* keys in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.4 | ZAI_API_KEY in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.5 | Vault tokens generated | Manual verification | `invoke vault.setup-tokens` | P0 |

### AC7.6: Backend Configuration & Secrets Sync

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.6.1 | Config syncs with .env.example | `TestConfigContract.test_config_sync_with_env_example` | `infra/test_config_contract.py` | P0 |
| AC7.6.2 | Required secrets documented | Manual verification | `.env.example` | P0 |

### AC7.7: Health Checks

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.7.1 | Health endpoint returns 200 | `test_health_when_all_services_healthy()` | `infra/test_main.py` | P0 |
| AC7.7.2 | Health check with services down | `test_health_returns_503_on_database_failure()`, `test_health_fails_when_redis_configured_but_unavailable()`, `test_health_returns_503_on_s3_failure()` | `infra/test_main.py` | P0 |

### AC7.8: Docker & CI Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.8.1 | Moon local CLI contract is versioned without PR CI bootstrap | `test_moon_cli_static_contract_available()` | `infra/test_ci_config.py` | P0 |
| AC7.8.2 | Docker compose integrity | `test_docker_compose_integrity()` | `infra/test_ci_config.py` | P0 |
| AC7.8.3 | Moon project graph contract is declared in repo config | `test_moon_project_graph_static_contract()` | `infra/test_ci_config.py` | P0 |

### AC7.9: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.9.1 | PostgreSQL healthy (manual) | `invoke finance_report.postgres.status` | Infra2 commands | P0 |
| AC7.9.2 | Redis healthy (manual) | `invoke finance_report.redis.status` | Infra2 commands | P0 |
| AC7.9.3 | App healthy (manual) | `invoke finance_report.app.status` | Infra2 commands | P0 |
| AC7.9.4 | Domain accessible (manual) | `curl https://report.${INTERNAL_DOMAIN}` | Smoke tests | P0 |
| AC7.9.5 | API functional (manual) | `curl https://report.${INTERNAL_DOMAIN}/api/health` | Smoke tests | P0 |
| AC7.9.6 | Secrets in Vault (manual) | No secrets in Dokploy env vars | Manual verification | P0 |
| AC7.9.7 | Backend health endpoint | `test_health_when_all_services_healthy()` | `infra/test_main.py` | P0 |
| AC7.9.8 | Config contract validation | `TestConfigContract` class | `infra/test_config_contract.py` | P0 |

### AC7.10: Promote and Release Pipeline Integrity

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.10.1 | `production-release.yml` promotes the staging-validated image to `vX.Y.Z` instead of rebuilding from source | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.2 | Release fails closed if no staging-validated SHA image exists or if digests differ | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.3 | Workflow summary records released commit, source CI run, promoted image digest, and no rebuild | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.4 | Deployment and CI SSOTs document the promote-not-rebuild consistency ladder | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.5 | Retain `workflow_dispatch` dry-run to prove the release/promote path without mutating production | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |

### AC7.11: Database Migration Risk Governance

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.11.1 | Backend Alembic migrations are covered by a machine-readable migration risk manifest | `test_AC7_11_1_migration_risk_manifest_covers_backend_migrations` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.2 | High and critical migration risk entries require release proof notes for staging, production preflight, and rollback/expand-contract strategy | `test_AC7_11_2_high_and_critical_migrations_require_release_proof` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.3 | Destructive upgrade operations cannot be classified below critical risk | `test_AC7_11_3_destructive_migrations_must_be_classified_critical` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.4 | CI lint and production release dry-run execute the migration risk contract and publish release context | `test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract` | `tests/tooling/test_migration_risk_contract.py` | P0 |

### AC7.12: Delivery App/Infra-boundary calibration (#876)

> Framework doc-of-record lives in issue #876 (G1–P3). This table tracks only ACs that already have a test; the rest land with their implementing PRs.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.12.6 | SSOT (`environments.md`) defines the data axis (empty / staging / anonymized prod snapshot) and the four data red lines (RL-DATA-1..4): a PR sha never runs on prod data; prod data is anonymized before leaving prod; non-prod object storage holds no real uploads; a backup is not an anonymized snapshot | `test_AC7_12_6_environments_define_data_axis_and_red_lines` | `tests/tooling/test_data_red_lines_contract.py` | P1 |
| AC7.12.8 | The published `:<sha>` front-end image is environment-independent (same-origin `/api`, no environment domain baked in); a contract test fails if a concrete environment domain appears in the published image | `test_AC7_12_8_published_frontend_image_has_no_baked_env_domain` | `tests/tooling/test_frontend_same_origin_contract.py` | P0 |


## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **PostgreSQL healthy** | `invoke finance_report.postgres.status` returns OK | 🔴 Critical |
| **Redis healthy** | `invoke finance_report.redis.status` returns OK | 🔴 Critical |
| **App healthy** | `invoke finance_report.app.status` returns OK | 🔴 Critical |
| **Domain accessible** | `curl https://report.${INTERNAL_DOMAIN}` returns 200 | 🔴 Critical |
| **API functional** | `curl https://report.${INTERNAL_DOMAIN}/api/health` returns OK | 🔴 Critical |
| **Secrets in Vault** | No secrets in Dokploy env vars or disk | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Database backup automation | Scheduled pg_dump | ⏳ |
| Monitoring integration | SigNoz traces | ⏳ |
| Auto-scaling | Resource limits tuning | ⏳ |

### 🚫 Not Acceptable Signals

- Secrets exposed in environment variables
- Database connection failures
- Frontend cannot reach backend API
- SSL certificate errors

---

## 📚 SSOT References

- [Infra2 AGENTS.md](https://github.com/wangzitian0/infra2/blob/main/AGENTS.md) - AI behavior guidelines
- [platform.domain.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/platform.domain.md) - Domain routing rules
- [bootstrap.vars_and_secrets.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/bootstrap.vars_and_secrets.md) - Secrets management
- [db.vault-integration.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/db.vault-integration.md) - Vault integration pattern

---

## 🔗 Deliverables

- [x] `repo/finance_report/finance_report/README.md`
- [x] `repo/finance_report/finance_report/01.postgres/` (full deploy structure)
- [x] `repo/finance_report/finance_report/02.redis/` (full deploy structure)
- [x] `repo/finance_report/finance_report/10.app/` (full deploy structure)
- [x] Update `repo/finance_report/README.md` (if exists)
- [x] Link to Infra-009 in infra2 docs

---

## 🔗 Related Projects

- **Infra2 Reference**: [Infra-009.finance_report_deploy.md](https://github.com/wangzitian0/infra2/blob/main/docs/project/Infra-009.finance_report_deploy.md)

---

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/deployment.md](../ssot/deployment.md) — deployment architecture, Vault, staging, and release rationale.
- [../ssot/environments.md](../ssot/environments.md) — six-environment taxonomy and isolation model.

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Phase 1 | Infrastructure setup | 1h |
| Phase 2 | PostgreSQL deployment | 2h |
| Phase 3 | Redis deployment | 1h |
| Phase 4 | App deployment | 3h |
| Phase 5 | Vault secrets | 1h |
| Phase 6 | Verification | 2h |

**Total estimate**: 10 hours (1 week buffer)

---

## 📝 Change Log

| Date | Change |
|------|--------|
| 2026-01-10 | Project created, submodule added |
| 2026-01-27 | All phases completed, production deployment verified |
