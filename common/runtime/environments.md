# Five Environments SSOT

> **SSOT Key**: `environments` | How the application consumes environments. Canonical environment taxonomy and OTLP contract live in [infra2 environment SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/core.environments.md#telemetry-identity) and [infra2 observability SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.observability.md).

## Environment Overview

| Env | Trigger | Runtime | DB / Bucket Isolation |
|---|---|---|---|
| **Local Dev** | `make backend` | Host uvicorn/next + Podman/Docker | `finance_report` / `statements` |
| **GitHub CI** | Push/PR (`ci.yml`) | Ephemeral GitHub services | `finance_report_test` |
| **Staging** | Manual (`workflow_dispatch` via `infra2`) | GHCR `:vX.Y.Z` image | Dedicated DB/Redis, `finance-report-staging` bucket (`staging`) |
| **Production** | Manual release, owner-approved (`workflow_dispatch`) | GHCR `:vX.Y.Z` image | Dedicated DB/Redis, `finance-report-production` bucket (`prod`) |

Transient `Preview` slots provisioned by `infra2` (`deploy_v2`) use the `staging` data lane (`EnvConfig.data_default`).

### Host Shell Boundaries

On Windows, run commands inside WSL Ubuntu (`wsl.exe -d Ubuntu --cd ... --exec /bin/bash -lc "..."`) rather than PowerShell/Git Bash so `podman`, `op`, `gh`, `uv`, and `nvm` resolve consistently.

## Container Naming Patterns

- **Local Dev / CI**: `finance-report-{service}${ENV_SUFFIX:-}` (hyphen; DB host `db`).
- **Staging / Production**: `finance_report-{service}${ENV_SUFFIX}` (underscore; `ENV_SUFFIX=-staging` on Staging, empty on Production).

## Data Lane & Red Lines

The deploy front door is `deploy_v2(service, type, version_ref, iac_ref)`; `data_lane` is derived from `EnvConfig.data_default` (`Staging` -> `staging`, `Preview` -> `staging`, `Production` -> `prod`) and is not a public `deploy_v2` coordinate.

### Data sources

- **empty**: freshly migrated DB + fixtures (GitHub CI, preview DBs).
- **staging**: non-prod testing data lane for Staging and Preview.
- **anonymized prod snapshot**: planned anonymized shape feed (#893).

### Data red lines

- **RL-DATA-1**: Unreviewed **PR** code must never run against **prod data**.
- **RL-DATA-2**: **Prod** data must be **anonymized** before leaving the prod network.
- **RL-DATA-3**: Non-prod **object storage** holds only **synthetic** documents, no real uploads.
- **RL-DATA-4**: A **backup** (real encrypted DR) is separate from an anonymized **snapshot**.

Related: [development.md](../meta/development.md) · [ci-cd.md](../testing/ci-cd.md) · [deployment.md](./deployment.md)
