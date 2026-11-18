# EPIC-007: Production Deployment

> **Status**: Complete
> **Vision Anchor**: `decision-7-tech-stack`

Deploys Finance Report via `infra2` (`deploy_v2`) with isolated Postgres (`01.pg`), Redis (`02.redis`), shared MinIO (`03.minio`), and Vault-agent secret injection (`10.app`). Domain: `report.${INTERNAL_DOMAIN}`. Runtime specifications live in [common/runtime/deployment.md](../../common/runtime/deployment.md) and [common/meta/readme.md](../../common/meta/readme.md).
