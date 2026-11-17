# EPIC-007: Production Deployment

> **Status**: Complete
> **Vision Anchor**: `decision-7-tech-stack`

Deploys Finance Report via `infra2` (`deploy_v2`) with isolated Postgres (`01.pg`), Redis (`02.redis`), shared MinIO (`03.minio`), and Vault-agent secret injection (`10.app`). Domain: `report.${INTERNAL_DOMAIN}`. Package-owned ACs (`AC-runtime.*`, `AC-meta.*`) live in [common/runtime/contract.py](../../common/runtime/contract.py) and [common/meta/contract.py](../../common/meta/contract.py).

## Horizontal Infrastructure Residue

| ID | Requirement | Test Function | File | Priority |
|---|---|---|---|---|
| AC7.1.1 | Infra2 owns deployment source independently | Receiver-boundary verification | Git | P0 | <!-- epic-owned: horizontal -->
| AC7.1.2 | Finance_report directory structure | Infra2 verification | `finance_report/` in infra2 | P0 | <!-- epic-owned: horizontal -->
| AC7.1.3 | README documentation exists | Infra2 verification | `finance_report/finance_report/README.md` in infra2 | P0 | <!-- epic-owned: horizontal -->
| AC7.2.1 | PostgreSQL container configured | Infra2 verification | `finance_report/finance_report/01.postgres/compose.yaml` | P0 | <!-- epic-owned: horizontal -->
| AC7.2.2 | Vault-agent sidecar present | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.2.3 | Vault policy for postgres | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.2.4 | Secrets template for postgres | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.2.5 | PostgresDeployer class exists | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.3.1 | Redis container configured | Infra2 verification | `finance_report/finance_report/02.redis/compose.yaml` | P0 | <!-- epic-owned: horizontal -->
| AC7.3.2 | Vault-agent sidecar present | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.3.3 | Vault policy for redis | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.3.4 | Secrets template for redis | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.3.5 | RedisDeployer class exists | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.4.1 | App container configured | Infra2 verification | `finance_report/finance_report/10.app/compose.yaml` | P0 | <!-- epic-owned: horizontal -->
| AC7.4.2 | Vault-agent sidecar present | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.4.3 | Vault policy for app | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.4.4 | Secrets template for app | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.4.5 | Traefik labels for domain | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.4.6 | AppDeployer class exists | Infra2 verification | same infra2 component | P0 | <!-- epic-owned: horizontal -->
| AC7.5.1 | DATABASE_URL in Vault | Manual verification | Vault secret path | P0 | <!-- epic-owned: horizontal -->
| AC7.5.2 | REDIS_URL in Vault | Manual verification | Vault secret path | P0 | <!-- epic-owned: horizontal -->
| AC7.5.3 | S3_* keys in Vault | Manual verification | Vault secret path | P0 | <!-- epic-owned: horizontal -->
| AC7.5.4 | ZAI_API_KEY in Vault | Manual verification | Vault secret path | P0 | <!-- epic-owned: horizontal -->
| AC7.5.5 | Vault AppRole creds provisioned | Manual verification | `invoke vault.setup-approle` | P0 | <!-- epic-owned: horizontal -->
| AC7.6.2 | Required secrets documented | Manual verification | `.env.example` | P0 | <!-- epic-owned: horizontal -->
| AC7.9.1 | PostgreSQL healthy (manual) | `invoke finance_report.postgres.status` | Infra2 commands | P0 | <!-- epic-owned: horizontal -->
| AC7.9.2 | Redis healthy (manual) | `invoke finance_report.redis.status` | Infra2 commands | P0 | <!-- epic-owned: horizontal -->
| AC7.9.3 | App healthy (manual) | `invoke finance_report.app.status` | Infra2 commands | P0 | <!-- epic-owned: horizontal -->
| AC7.9.4 | Domain accessible (manual) | `curl https://report.${INTERNAL_DOMAIN}` | Smoke tests | P0 | <!-- epic-owned: horizontal -->
| AC7.9.5 | API functional (manual) | `curl https://report.${INTERNAL_DOMAIN}/api/health` | Smoke tests | P0 | <!-- epic-owned: horizontal -->
| AC7.9.6 | Secrets in Vault (manual) | No secrets in Dokploy env vars | Manual verification | P0 | <!-- epic-owned: horizontal -->
