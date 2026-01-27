# EPIC-007: Production Deployment

> **Status**: 🟡 In Progress  
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
- [ ] Create `repo/finance_report/finance_report/` directory structure
- [ ] Create README.md for finance_report layer

### Phase 2: Database Layer (01.postgres)

- [ ] `compose.yaml` - PostgreSQL 16 with vault-agent sidecar
- [ ] `deploy.py` - PostgresDeployer class
- [ ] `shared_tasks.py` - Health check tasks
- [ ] `vault-agent.hcl` - Vault agent configuration
- [ ] `vault-policy.hcl` - Vault policy for postgres
- [ ] `secrets.ctmpl` - Secrets template
- [ ] `README.md` - Documentation

### Phase 3: Cache Layer (02.redis)

- [ ] `compose.yaml` - Redis with vault-agent sidecar
- [ ] `deploy.py` - RedisDeployer class
- [ ] `shared_tasks.py` - Health check tasks
- [ ] `vault-agent.hcl` - Vault agent configuration
- [ ] `vault-policy.hcl` - Vault policy for redis
- [ ] `secrets.ctmpl` - Secrets template
- [ ] `README.md` - Documentation

### Phase 4: Application Layer (10.app)

- [ ] `compose.yaml` - Backend + Frontend with vault-agent sidecar
- [ ] `deploy.py` - AppDeployer class
- [ ] `shared_tasks.py` - Health check tasks
- [ ] `vault-agent.hcl` - Vault agent configuration
- [ ] `vault-policy.hcl` - Vault policy for app
- [ ] `secrets.ctmpl` - Secrets template (DATABASE_URL, REDIS_URL, S3_*, OPENROUTER_API_KEY)
- [ ] `README.md` - Documentation
- [ ] Traefik labels for `report.${INTERNAL_DOMAIN}`

### Phase 5: Vault Secrets Setup

- [ ] Write secrets to Vault:
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
    - OPENROUTER_API_KEY
  ```
- [ ] Generate service tokens via `invoke vault.setup-tokens`

### Phase 6: Deployment & Verification

- [ ] Deploy postgres: `invoke finance_report.postgres.setup`
- [ ] Deploy redis: `invoke finance_report.redis.setup`
- [ ] Deploy app: `invoke finance_report.app.setup`
- [ ] Verify health checks
- [ ] Test `https://report.${INTERNAL_DOMAIN}`

---

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

- [ ] `repo/finance_report/finance_report/README.md`
- [ ] `repo/finance_report/finance_report/01.postgres/` (full deploy structure)
- [ ] `repo/finance_report/finance_report/02.redis/` (full deploy structure)
- [ ] `repo/finance_report/finance_report/10.app/` (full deploy structure)
- [ ] Update `repo/finance_report/README.md` (if exists)
- [ ] Link to Infra-009 in infra2 docs

---

## 🔗 Related Projects

- **Infra2 Reference**: [Infra-009.finance_report_deploy.md](https://github.com/wangzitian0/infra2/blob/main/docs/project/Infra-009.finance_report_deploy.md)

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

