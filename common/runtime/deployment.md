# Deployment Architecture SSOT

> **SSOT Key**: `deployment` | Deployment workflows, Vault secret injection, and release boundaries. See [environments.md](./environments.md).

## One-Way Repository Model

- **Local/CI**: `/docker-compose.yml`.
- **Staging/Production**: `infra2`-owned (`reconcile-iac-inputs.yml`, `harness/repos.yaml`). Finance Report pins `infra2-sdk` (`apps/backend/pyproject.toml` + `uv.lock`, verified by `common/runtime/sdk_pin.py`) and declares `runtime-hooks.manifest.json` (`smoke`, `preview_gate`, `staging_gate`, `scheduled_audit`).

## Secret Injection Flow

Production/staging use `vault-agent` sidecar (`VAULT_ROLE_ID` / `VAULT_SECRET_ID` AppRole) rendering `/secrets/.env` before `alembic upgrade head` and Uvicorn start. `apps/backend/src/config.py` declares env vars (`common/runtime/required-env.generated.json`); `Bootloader._check_static_config` fails closed in protected runtimes if `SECRET_KEY`, `DATABASE_URL`, or `S3_SECRET_KEY` use dev defaults.

## Staging & Production Release Trains

- **Staging**: Manual dispatch only (`workflow_dispatch` in `infra2`) consuming `:vX.Y.Z` images promoted from `main` CI `:<sha7>` via `ci.yml` (`promote-release-images`).
- **Production**: Manual `workflow_dispatch` (`deploy_v2`, `type=prod`) after staging passes, requiring owner approval and presence, verifying image digests and pre/post `/api/health.git_sha` and `IAC_CONFIG_HASH`.
- **Migrations**: Run `python tools/check_migration_risk.py` against `common/meta/data/migration-risk.yaml`. Incident triage: [runtime-incident-response.md](./runtime-incident-response.md).
