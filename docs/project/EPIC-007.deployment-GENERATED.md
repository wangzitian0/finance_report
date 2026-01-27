# EPIC-007: Production Deployment — GENERATED

> **Auto-generated implementation summary** — Do not edit manually.
> **Last updated**: 2026-01-27
> **Source EPIC**: [EPIC-007.deployment.md](./EPIC-007.deployment.md)

---

## 📋 Implementation Summary

EPIC-007 deploys the Finance Report application to production using Dokploy + vault-init pattern. The deployment architecture includes independent PostgreSQL and Redis instances per project, with MinIO shared from the platform.

### Target Domain

`report.${INTERNAL_DOMAIN}` (e.g., `report.zitian.party`)

### Completed Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| Infra2 submodule | `repo/` | ✅ Complete |
| PostgreSQL deployment | `repo/finance_report/finance_report/01.postgres/` | ⏳ In Progress |
| Redis deployment | `repo/finance_report/finance_report/02.redis/` | ⏳ In Progress |
| App deployment (BE+FE) | `repo/finance_report/finance_report/10.app/` | ⏳ In Progress |
| Vault secrets | `secret/data/finance_report/<env>/*` | ⏳ In Progress |
| Traefik routing | Domain routing via labels | ⏳ In Progress |

---

## 🏗️ Architecture

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

## 📁 Infrastructure Structure

### Directory Layout (repo/finance_report/finance_report/)

```
repo/finance_report/finance_report/
├── README.md                    # Project-level documentation
├── 01.postgres/
│   ├── compose.yaml             # PostgreSQL 16 + vault-agent
│   ├── deploy.py                # PostgresDeployer class
│   ├── shared_tasks.py          # Health check tasks
│   ├── vault-agent.hcl          # Vault agent config
│   ├── vault-policy.hcl         # Vault policy
│   ├── secrets.ctmpl            # Secrets template
│   └── README.md
├── 02.redis/
│   ├── compose.yaml             # Redis + vault-agent
│   ├── deploy.py                # RedisDeployer class
│   ├── shared_tasks.py          # Health check tasks
│   ├── vault-agent.hcl
│   ├── vault-policy.hcl
│   ├── secrets.ctmpl
│   └── README.md
└── 10.app/
    ├── compose.yaml             # Backend + Frontend + vault-agent
    ├── deploy.py                # AppDeployer class
    ├── shared_tasks.py          # Health check tasks
    ├── vault-agent.hcl
    ├── vault-policy.hcl
    ├── secrets.ctmpl            # DATABASE_URL, REDIS_URL, S3_*, etc.
    └── README.md
```

---

## 🔐 Vault Secrets Structure

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
  - OTEL_EXPORTER_OTLP_ENDPOINT (optional)
  - OTEL_EXPORTER_OTLP_HEADERS (optional)
```

### Environment Variables

| Variable | Source | Required |
|----------|--------|----------|
| `DATABASE_URL` | Vault | ✅ Yes |
| `REDIS_URL` | Vault | ✅ Yes |
| `S3_ENDPOINT` | Vault | ✅ Yes |
| `S3_ACCESS_KEY` | Vault | ✅ Yes |
| `S3_SECRET_KEY` | Vault | ✅ Yes |
| `S3_BUCKET` | Vault | ✅ Yes |
| `OPENROUTER_API_KEY` | Vault | ❌ Optional (AI features) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Vault | ❌ Optional (logging) |

---

## 🚀 Deployment Commands

### Setup (First-time deployment)

```bash
# Deploy PostgreSQL
uv run invoke finance_report.postgres.setup

# Deploy Redis
uv run invoke finance_report.redis.setup

# Deploy Application
uv run invoke finance_report.app.setup
```

### Status Checks

```bash
# Check PostgreSQL
uv run invoke finance_report.postgres.status

# Check Redis
uv run invoke finance_report.redis.status

# Check Application
uv run invoke finance_report.app.status

# Full health check
uv run invoke finance_report.status
```

### Restart Services

```bash
# Restart after Vault template update
uv run invoke finance_report.app.restart

# Restart with config hash update
uv run invoke finance_report.app.restart --update-config-hash
```

---

## 🐳 Docker Compose Configuration

### 10.app/compose.yaml (Key sections)

```yaml
services:
  backend:
    image: ghcr.io/wangzitian0/finance_report/backend:${TAG:-latest}
    environment:
      - IAC_CONFIG_HASH=${IAC_CONFIG_HASH:-default}
    env_file:
      - /run/secrets/app.env
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.finance-report-api.rule=Host(`report.${INTERNAL_DOMAIN}`) && PathPrefix(`/api`)"
      - "traefik.http.routers.finance-report-api.entrypoints=websecure"
      - "traefik.http.routers.finance-report-api.tls.certresolver=letsencrypt"
    networks:
      - traefik-public
      - finance-report-internal

  frontend:
    image: ghcr.io/wangzitian0/finance_report/frontend:${TAG:-latest}
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.finance-report-web.rule=Host(`report.${INTERNAL_DOMAIN}`)"
      - "traefik.http.routers.finance-report-web.entrypoints=websecure"
      - "traefik.http.routers.finance-report-web.tls.certresolver=letsencrypt"
    networks:
      - traefik-public

  vault-agent:
    image: hashicorp/vault:1.15
    volumes:
      - ./vault-agent.hcl:/etc/vault/agent.hcl:ro
      - ./secrets.ctmpl:/etc/vault/secrets.ctmpl:ro
      - secrets:/run/secrets
    command: agent -config=/etc/vault/agent.hcl

volumes:
  secrets:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs

networks:
  traefik-public:
    external: true
  finance-report-internal:
    driver: bridge
```

---

## 📏 Acceptance Criteria Status

### 🟢 Must Have

| Criterion | Status | Verification |
|-----------|--------|--------------|
| PostgreSQL healthy | ⏳ | `invoke finance_report.postgres.status` returns OK |
| Redis healthy | ⏳ | `invoke finance_report.redis.status` returns OK |
| App healthy | ⏳ | `invoke finance_report.app.status` returns OK |
| Domain accessible | ⏳ | `curl https://report.${INTERNAL_DOMAIN}` returns 200 |
| API functional | ⏳ | `/api/health` returns OK |
| Secrets in Vault | ⏳ | No secrets in Dokploy env vars or disk |

### 🌟 Nice to Have

| Criterion | Status | Notes |
|-----------|--------|-------|
| Database backup automation | ⏳ | Scheduled pg_dump planned |
| Monitoring integration | ✅ | SigNoz traces (see EPIC-010) |
| Auto-scaling | ⏳ | Resource limits tuning |

---

## 🔗 Related Documentation

### SSOT References

- [deployment.md](../ssot/deployment.md) — Deployment architecture SSOT
- [observability.md](../ssot/observability.md) — OTEL logging configuration

### Infra2 References

- [Infra2 AGENTS.md](../../repo/AGENTS.md) — AI behavior guidelines
- [platform.domain.md](../../repo/docs/ssot/platform.domain.md) — Domain routing rules
- [bootstrap.vars_and_secrets.md](../../repo/docs/ssot/bootstrap.vars_and_secrets.md) — Secrets management
- [db.vault-integration.md](../../repo/docs/ssot/db.vault-integration.md) — Vault integration pattern

### Related EPICs

- [EPIC-010.signoz-logging.md](./EPIC-010.signoz-logging.md) — SigNoz logging integration
- [Infra-009.finance_report_deploy.md](../../repo/docs/project/Infra-009.finance_report_deploy.md) — Infra2 side of deployment

---

## ✅ Verification Commands

```bash
# Verify domain is accessible
curl -I https://report.zitian.party

# Verify API health
curl https://report.zitian.party/api/health

# Verify frontend loads
open https://report.zitian.party

# Check container status
uv run invoke finance_report.status

# View logs
python scripts/debug.py logs backend --env production
python scripts/debug.py logs frontend --env production
```

---

## 📅 Timeline

| Phase | Content | Estimated Hours | Status |
|-------|---------|-----------------|--------|
| Phase 1 | Infrastructure setup | 1h | ✅ Complete |
| Phase 2 | PostgreSQL deployment | 2h | ⏳ In Progress |
| Phase 3 | Redis deployment | 1h | ⏳ Pending |
| Phase 4 | App deployment | 3h | ⏳ Pending |
| Phase 5 | Vault secrets | 1h | ⏳ Pending |
| Phase 6 | Verification | 2h | ⏳ Pending |

**Total estimate**: 10 hours (1 week buffer)

---

*This file is auto-generated from EPIC-007 implementation. For goals and acceptance criteria, see [EPIC-007.deployment.md](./EPIC-007.deployment.md).*
