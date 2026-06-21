# Six Environments SSOT

> **SSOT Key**: `environments`
> **App-side view** of how this software *consumes* deployment environments —
> naming conventions and isolation mechanisms the backend relies on.

*Extracted from [development.md](./development.md) — see that file for Moon commands and local setup.*

!!! warning "Environment taxonomy & telemetry identity are owned by infra2"
    The canonical **environment taxonomy** and the **observability contract**
    (OTLP collector endpoint, `deployment.environment` surface alias and its
    allowed values, and the underlying short-commit-SHA `service.version`
    telemetry identity) are **owned and issued by infra2** (runtime), not by this
    App doc (software):

    - [`repo/docs/ssot/core.environments.md#telemetry-identity`](../../repo/docs/ssot/core.environments.md#telemetry-identity)
      — environment taxonomy + telemetry identity.
    - [`repo/docs/ssot/ops.observability.md`](../../repo/docs/ssot/ops.observability.md)
      — single no-suffix OTLP collector and OTLP env vars.

    This App doc describes only how the App **consumes** those environments
    (which image/data runs where, container/DB/bucket naming the backend connects
    to). The **App must NOT re-define environments or the observability
    contract**; it consumes the infra2-issued values via `config.py` and
    fast-fails on missing required values. Do not restate per-environment
    collector endpoints or `deployment.environment` values here — see Infra-014 /
    `AGENTS.md` for the boundary.

---

## Environment Overview

> **Core Principle**: "One Codebase, Multiple Environments" — Local uses containers + namespace isolation, CI emphasizes consistency, Production uses image deployment.

| # | Environment | URL | Trigger | Code Runtime | Infrastructure | Database | Isolation |
|---|-------------|-----|---------|--------------|----------------|----------|-----------|
| **1** | **Local Dev** | `localhost:3000` | Manual<br>`moon run :dev -- --backend` | Source (Host)<br>uvicorn/next dev | Shared Containers<br>(Podman/Docker) | `finance_report` | Container name suffix |
| **2** | **Local CI** | `localhost:3000` | Manual<br>`moon run :lint && moon run :test` | Source (Host)<br>pytest | Shared Containers<br>(Podman/Docker) | `finance_report_test_{namespace}` | DB/bucket name |
| **3** | **GitHub CI** | - | Push/PR<br>`ci.yml` | Source (Runner)<br>pytest | GitHub Services<br>(Ephemeral) | `finance_report_test` | Job isolation |
| **4** | **PR Preview** | Required gate: `http://localhost:8080` inside GitHub runner<br>Manual inspection: optional `report-pr-<N>.zitian.party` | PR push — synchronous `pull_request` runner E2E<br>Manual `workflow_dispatch` persistent preview | Runner compose stack for merge gate<br>On-demand Dokploy host-build for inspection | GitHub runner containers for merge gate<br>Optional Dokploy preview compose | Ephemeral Postgres/MinIO | Runner `COMPOSE_PROJECT_NAME=fr-e2e-<run>-<attempt>`<br>Dokploy `report-pr-<N>` alias |
| **5** | **Staging** | `report-staging.zitian.party` | **Manual**<br>`staging-deploy.yml` (`workflow_dispatch`) | **Docker Images**<br>(GHCR) | Dedicated infra2<br>+ Shared Platform | Dedicated DB/Redis | Bucket name<br>`-staging` |
| **6** | **Production** | `report.zitian.party` | Manual release<br>`production-release.yml` | **Docker Images**<br>(GHCR) | Dedicated infra2<br>+ Shared Platform | Dedicated DB/Redis | Bucket name |

Environment taxonomy is not the delivery pipeline stage count. The CI/CD model
is documented in [ci-cd.md](./ci-cd.md) as a sparse environment x pipeline stage
matrix: environments are where proof runs, pipeline stages are what quality gate
runs, and GitHub Actions jobs are implementation lanes for selected cells.

---

## Key Differences

### Local Environments (Dev + CI)

**Local Dev** — One shared set of containers, isolated by **different database names**:
- Uses `docker-compose.yml` (Profile: `infra`)
- **Persistent**: Manually started, data preserved across runs
- Isolation: Multiple repo copies use **namespace-aware DB names** (`finance_report`, `finance_report_dev_branch_a`, etc.)
- S3: Shared local MinIO with namespace-aware buckets (`statements`, `statements-branch-a`)
- Command: `moon run :dev -- --backend`

**Local CI** — Reuses Local Dev containers, creates **temporary test databases**:
- Uses same `docker-compose.yml` (Profile: `infra`)
- **Ephemeral data**: Test DB reset before each run, worker DBs auto-cleaned
- Isolation: `finance_report_test_{namespace}` + worker DBs (`_gw0`, `_gw1`, etc.); long namespaces are hash-shortened to keep DB names and `statements-{namespace}` buckets within 63-character backend limits.
- Command: `moon run :lint && moon run :test` (**same gate family as GitHub CI**; GitHub adds sharding, frontend coverage, tooling coverage, traceability, and image validation)

### Host Shell Boundaries

Local Dev and Local CI are POSIX-shell environments. On Windows, the supported
host is WSL Ubuntu, not native Windows PowerShell. WSL tools such as
`/usr/bin/podman`, `/usr/bin/op`, `/usr/local/bin/yq`, `/usr/bin/jq`,
`/usr/bin/direnv`, and WSL `gh` do not appear in Windows PATH automatically.
Windows tools installed with Scoop, including Python or `uv`, likewise do not
appear inside WSL.

The Codex Windows runner follows the Windows side of this split: it may see
Scoop Python and a non-interactive PowerShell PATH while missing WSL-only `gh`,
`podman`, `op`, or Python packages. Repo commands should enter WSL explicitly:

```powershell
wsl.exe -d Ubuntu --cd /home/<user>/workspace/finance_report --exec /bin/bash -lc "moon run :lint"
```

Non-interactive shells usually do not load the same profile files as an
interactive terminal. Treat PATH, `NVM_DIR`, and tool locations as part of the
environment contract; bootstrap and automation commands must set them explicitly
before invoking `moon`, `uv`, `npm`, `gh`, Docker, or Podman.

### GitHub Environments

**GitHub CI** — Temporary services, runs same commands as Local CI:
- Uses GitHub Actions `services:` (ephemeral Postgres container)
- **Completely ephemeral**: Destroyed after job finishes
- Database: `finance_report_test` (no namespace needed, job-isolated)
- Runtime, test, script, CI, dependency, and coverage-policy changes run the full backend/frontend/unified coverage gate.
- Lightweight documentation, markdown, issue-template, and `.github/workflows/docs.yml` changes skip the heavy backend/frontend/coverage jobs while still running lint, SSOT checks, AC traceability, and the final aggregate check.

PR validation is split into two independent things (issue #839):

**In-runner E2E** — the per-PR validation gate:
- Runs after the matching PR `CI` workflow completes successfully (the `e2e`
  job in `pr-test.yml`). Failed, cancelled, timed-out, non-PR, forked, or
  already-closed CI runs do not create a preview.
- Stands up the full stack **inside the GitHub runner** via
  `docker compose up --build` (base compose + `docker-compose.ci-e2e.yml`,
  which adds an nginx single-origin edge), runs the non-LLM E2E against
  `http://localhost:8080`, then **always tears the stack down**
  (`docker compose down -v --remove-orphans`) so nothing leaks.
- **Image-free at registry level**: builds locally in the runner and pushes
  nothing; no PR preview image, no GHCR tag, no Dokploy deploy, no shared VPS,
  and no SSL wait. This is what keeps E2E coverage cheap and fast.
- **No automatic persistent Dokploy URL**: the pull-request gate comments the
  validation result on the PR instead of publishing a click-through preview URL.

**Persistent PR Preview (Dokploy)** — manual, non-blocking inspection:
- The `deploy-preview` job still exists, but runs only by manual
  `workflow_dispatch` after the in-runner E2E gate passes. It is not merge
  authority.
- It currently uses the app-side `tools/pr_preview_lifecycle.py` path:
  Dokploy clones the PR branch and builds from source on the host. It does not
  pull a GHCR PR image and it is not the infra2 `deploy_v2 preview/*` path.
- Cleanup uses `tools/pr_preview_lifecycle.py --action cleanup`, is idempotent,
  and removes the persistent Dokploy compose on PR close/manual cleanup. Scheduled
  `PR Preview Cleanup` remains as bounded reconciliation for stale Dokploy
  resources.

### Production Environments (Staging + Production)

**Staging** — Manually deployed from a release `version_ref`:
- **Image deployment**: `staging-deploy.yml` requires an existing `vX.Y.Z`
  release tag as `version_ref`. `release-images.yml` promotes main-CI SHA
  images to that retained release tag, then staging deploys it via `deploy_v2`.
- Deployed to Dokploy **manually** via `staging-deploy.yml` (`workflow_dispatch`); it does **not** auto-follow push to main. CI is the development quality gate, not a staging deploy trigger.
- Persistent data, stable environment for QA
- Uses dedicated DB/Redis + shared Platform (SigNoz, MinIO with bucket isolation)

**Production** — Manual release process:
- **Image deployment**: Built from version tags (`v1.2.3`)
- Manual trigger after Staging validation
- Most stable environment, persistent data
- Uses dedicated DB/Redis + shared Platform

---

## Container Naming Patterns

| Environment | Backend Container | Frontend Container | Database | S3 Bucket |
|-------------|-------------------|---------------------|----------|-----------|
| **Local Dev** | `finance-report-backend` | `finance-report-frontend` | `finance_report` | `statements` |
| **Local CI** | *(uses Local Dev containers)* | *(uses Local Dev containers)* | `finance_report_test_{namespace}` | `statements-{namespace}` |
| **GitHub CI** | *(GitHub Services)* | *(N/A)* | `finance_report_test` | `statements` (mock) |
| **PR Preview** | Runner compose backend service | Runner compose frontend service | `postgres` service DNS | `minio` service DNS |
| **Staging** | `finance_report-backend-staging` | `finance_report-frontend-staging` | `finance_report-postgres-staging` | `finance-report-staging` |
| **Production** | `finance_report-backend` | `finance_report-frontend` | `finance_report-postgres` | `finance-report-production` |

**Note**: Two distinct conventions — do not conflate them.
- **Local Dev / CI** use the local `docker-compose.yml` pattern
  `finance-report-{service}${ENV_SUFFIX:-}` (**hyphen**, DB service `db`).
- **Staging / Production** are deployed by the infra2 IaC compose files
  (`repo/finance_report/finance_report/{01.postgres,02.redis,10.app}/compose.yaml`),
  whose `container_name` is `finance_report-{service}${ENV_SUFFIX}` (**underscore**,
  DB service `postgres`). The backend connects to these underscore hostnames — see
  `10.app/secrets.ctmpl` (`DATABASE_URL` → `finance_report-postgres${suffix}`,
  `REDIS_URL` → `finance_report-redis${suffix}`). `ENV_SUFFIX` is `-staging` for
  Staging, empty for Production.
- **PR Preview** raw compose removes fixed container names and uses compose service
  DNS on a project-scoped internal network, because Dokploy compose project names
  can change across retries while the PR route remains stable.

---

## Workflow Files Reference

| Workflow File | Environment | Trigger | Actions |
|---------------|-------------|---------|---------|
| `.github/workflows/ci.yml` | GitHub CI | Push/PR to main | Run lint, traceability, backend shards, frontend build/tests, common/tools coverage, unified coverage, and image validation |
| `.github/workflows/pr-test.yml` | PR Preview | PR opened/sync; manual dispatch for persistent preview | Run runner-local E2E as merge gate; optionally deploy/cleanup a non-blocking persistent Dokploy preview |
| `.github/workflows/release-images.yml` | Release images | Tag `vX.Y.Z` push | Promote main-CI SHA images to immutable release tags |
| `.github/workflows/staging-deploy.yml` | Staging | Manual (`workflow_dispatch`) | Deploy an existing release `version_ref` via deploy_v2, then smoke/E2E/AI-OCR gates |
| `.github/workflows/production-release.yml` | Production | Manual (`workflow_dispatch`) | Dry-run or deploy an existing release `version_ref` via deploy_v2 |

---

## Shared Platform Resources

The production Platform layer (SigNoz, MinIO, Traefik) runs as **Singleton** services.  Staging and PR environments use **logical isolation**:

| Service | Scope | Isolation Method | Example |
|---------|-------|------------------|---------|
| **SigNoz** | Singleton | infra2-owned telemetry identity (see below) | — |
| **MinIO** (Prod) | Singleton | Separate buckets | `finance-report-staging`, `finance-report-production` |
| **Postgres** | Dedicated | Separate containers/instances | One per environment |
| **Redis** | Dedicated | Separate containers/instances | One per environment |

SigNoz is a single global instance shared across environments; how App logs are
separated (the `deployment.environment` surface alias and its allowed values) is
part of the **infra2-owned** observability contract —
[`repo/docs/ssot/ops.observability.md`](../../repo/docs/ssot/ops.observability.md)
and
[`repo/docs/ssot/core.environments.md#telemetry-identity`](../../repo/docs/ssot/core.environments.md#telemetry-identity).
This App doc does not enumerate those values.

**Note**: PR Previews have **dedicated MinIO/DB/Redis** to allow destructive testing, but send logs to shared SigNoz.

---

## Test Strategy by Environment

| Environment | Tests Run | Purpose | Duration |
|-------------|-----------|---------|----------|
| **Local Dev** | None (manual testing) | Fast iteration | — |
| **Local CI** | Unit + integration with coverage policy from `common/coverage/policy.py` | Pre-push validation | ~30s |
| **GitHub CI** | Lint, AC traceability, unit + integration with unified coverage for heavy changes | Quality gate | ~7min heavy / lightweight skips heavy jobs |
| **PR Preview** | Runner-local health check + non-LLM E2E; optional manual Dokploy inspection | Merge validation + opt-in inspection | ~3-5min when enabled |
| **Staging** | Image deploy, smoke, non-LLM E2E, performance; AI/OCR regression recorded separately | **Deployment validation** + recorded full-provider validation | ~6min deploy + variable AI/OCR replay |
| **Production** | Health check only | Availability check | ~10s |

---

## Data Lane & Red Lines

An environment still has a **code artifact** and a **data lane**, but data is
not a public `deploy_v2` coordinate. The current deploy front door is
`deploy_v2(service, type, version_ref, iac_ref)`; `type` derives the environment,
and the execution layer derives `data_lane` from `EnvConfig.data_default` before
checking red-line predicates. Most of this project's risk (financial correctness,
Alembic migrations) lives on the data side, so the constraints below are **red
lines**, not preferences.

### Data sources

| Source | What it is | Used by (environment) |
|--------|------------|---------|
| **empty** | migrations freshly applied, seed/fixtures only | GitHub CI and runner-local E2E; new preview DBs start empty even when their derived lane label is `staging` |
| **staging** | non-prod operator lane / data accumulated by testing | Current `deploy_v2` default data lane for Staging and Preview |
| **anonymized prod snapshot** | the *shape* of real data, with amounts/PII anonymized | Planned `rehearsal` / staging data feed (#893) — fed by `snapshot-sync` |
| *(real prod data)* | live data | **Production only** |

**Current default**: `deploy_v2` derives the data lane from env config:
Staging → `staging`, Preview → `staging`, Production → `prod`. This is a
red-line classification input, not a public deploy parameter. The #893
snapshot-sync work must keep failure safe: a broken anonymizer may fall back to
empty/synthetic rehearsal data, but must never expose real prod data outside the
prod boundary.

### Data red lines

These are decided constraints; every environment inherits them. Each has a stable
label so a reword cannot silently drop it.

- **RL-DATA-1** — Unreviewed code (a **PR** sha) may never run against **prod data**.
- **RL-DATA-2** — **Prod** data must be **anonymized** before it leaves the prod
  network into any other environment (this is a financial system — real
  amounts/PII are an incident, not a convenience).
- **RL-DATA-3** — Non-prod **object storage** holds **no real uploads**; financial
  PDFs/scans can't be reliably anonymized, so use a **synthetic** document set.
- **RL-DATA-4** — A **backup** is **not** an anonymized **snapshot**: disaster
  recovery needs an encrypted *real-data* backup; the staging feed needs an
  *anonymized* one. They are two separate pipelines.

> Governance anchor: these red lines are the data-side counterpart of the
> App/Infra artifact boundary. Tracked by #876 (G2 #877); the migration-rehearsal
> use of the anonymized snapshot ties to AC7.11.

---

## Related

- [development.md](./development.md) — Moon commands and local setup
- [ci-cd.md](./ci-cd.md) — CI job structure and test optimization
- [deployment.md](./deployment.md) — Deployment architecture and workflows
- [docs/ssot/MANIFEST.yaml](./MANIFEST.yaml) — Concept ownership registry
