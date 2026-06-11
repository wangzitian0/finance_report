# Six Environments SSOT

> **SSOT Key**: `environments`
> **Source of Truth** for all deployment environments, naming conventions, and isolation mechanisms.

*Extracted from [development.md](./development.md) — see that file for Moon commands and local setup.*

---

## Environment Overview

> **Core Principle**: "One Codebase, Multiple Environments" — Local uses containers + namespace isolation, CI emphasizes consistency, Production uses image deployment.

| # | Environment | URL | Trigger | Code Runtime | Infrastructure | Database | Isolation |
|---|-------------|-----|---------|--------------|----------------|----------|-----------|
| **1** | **Local Dev** | `localhost:3000` | Manual<br>`moon run :dev -- --backend` | Source (Host)<br>uvicorn/next dev | Shared Containers<br>(Podman/Docker) | `finance_report` | Container name suffix |
| **2** | **Local CI** | `localhost:3000` | Manual<br>`moon run :lint && moon run :test` | Source (Host)<br>pytest | Shared Containers<br>(Podman/Docker) | `finance_report_test_{namespace}` | DB/bucket name |
| **3** | **GitHub CI** | - | Push/PR<br>`ci.yml` | Source (Runner)<br>pytest | GitHub Services<br>(Ephemeral) | `finance_report_test` | Job isolation |
| **4** | **PR Preview** | `http://localhost:8080` inside GitHub runner<br>**No persistent Dokploy URL** | Successful PR `CI` `workflow_run`<br>`pr-test.yml` | Runner compose stack<br>(local build, no registry push) | GitHub runner containers<br>(Per run) | Ephemeral Postgres/MinIO | `COMPOSE_PROJECT_NAME=fr-e2e-<run>-<attempt>` |
| **5** | **Staging** | `report-staging.zitian.party` | Push to main<br>`staging-deploy.yml` | **Docker Images**<br>(GHCR) | Dedicated infra2<br>+ Shared Platform | Dedicated DB/Redis | Bucket name<br>`-staging` |
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
- **No persistent Dokploy URL**: the workflow comments the validation result on
  the PR instead of publishing a click-through preview URL.

**Legacy PR Preview (Dokploy)** — cleanup-only compatibility:
- Historical PR previews may still exist from the former Dokploy flow. The
  current workflow removes those resources on PR close/merge, failed CI,
  cancelled CI, timed-out CI, and before a new successful runner preview.
- Cleanup uses `tools/pr_preview_lifecycle.py --action cleanup`, is idempotent,
  and does not build, push, preflight, or delete PR preview images.
- Scheduled `PR Preview Cleanup` remains as bounded reconciliation for stale
  historical Dokploy resources.

### Production Environments (Staging + Production)

**Staging** — Tracks latest `main` branch:
- **Image deployment**: Built from latest `main` commit after merge
- Deployed to Dokploy automatically on push to main
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
| **Staging** | `finance-report-backend-staging` | `finance-report-frontend-staging` | `finance-report-db-staging` | `finance-report-staging` |
| **Production** | `finance-report-backend` | `finance-report-frontend` | `finance-report-db` | `finance-report-production` |

**Note**: Container names follow the pattern `finance-report-{service}${ENV_SUFFIX}` from `docker-compose.yml` for fixed-name environments. PR Preview raw compose removes fixed container names and uses compose service DNS on a project-scoped internal network, because Dokploy compose project names can change across retries while the PR route remains stable. `ENV_SUFFIX` is `-pr-{N}` for PR Preview and `-staging` for Staging; empty for Production.

---

## Workflow Files Reference

| Workflow File | Environment | Trigger | Actions |
|---------------|-------------|---------|---------|
| `.github/workflows/ci.yml` | GitHub CI | Push/PR to main | Run lint, traceability, backend shards, frontend build/tests, common/tools coverage, unified coverage, and image validation |
| `.github/workflows/pr-test.yml` | PR Preview | PR opened/sync | Build images, deploy to Dokploy, cleanup on close |
| `.github/workflows/staging-deploy.yml` | Staging | Push to main | Build images (`:staging` tag), deploy |
| `.github/workflows/production-release.yml` | Production | Tag `v*.*.*` or manual | Build release images, deploy on manual trigger |

---

## Shared Platform Resources

The production Platform layer (SigNoz, MinIO, Traefik) runs as **Singleton** services.  Staging and PR environments use **logical isolation**:

| Service | Scope | Isolation Method | Example |
|---------|-------|------------------|---------|
| **SigNoz** | Singleton | `deployment.environment` tag | `staging`, `production`, `pr-47` |
| **MinIO** (Prod) | Singleton | Separate buckets | `finance-report-staging`, `finance-report-production` |
| **Postgres** | Dedicated | Separate containers/instances | One per environment |
| **Redis** | Dedicated | Separate containers/instances | One per environment |

**Note**: PR Previews have **dedicated MinIO/DB/Redis** to allow destructive testing, but send logs to shared SigNoz.

---

## Test Strategy by Environment

| Environment | Tests Run | Purpose | Duration |
|-------------|-----------|---------|----------|
| **Local Dev** | None (manual testing) | Fast iteration | — |
| **Local CI** | Unit + integration with coverage policy from `common/coverage/policy.py` | Pre-push validation | ~30s |
| **GitHub CI** | Lint, AC traceability, unit + integration with unified coverage for heavy changes | Quality gate | ~7min heavy / lightweight skips heavy jobs |
| **PR Preview** | Health check + non-LLM E2E against per-PR Dokploy environment | Opt-in on-demand inspection (not a per-PR gate) | ~3-5min when enabled |
| **Staging** | Image deploy, smoke, non-LLM E2E, performance; AI/OCR gate runs separately | **Deployment validation** + full validation | ~6min deploy + variable AI/OCR gate |
| **Production** | Health check only | Availability check | ~10s |

---

## Related

- [development.md](./development.md) — Moon commands and local setup
- [ci-cd.md](./ci-cd.md) — CI job structure and test optimization
- [deployment.md](./deployment.md) — Deployment architecture and workflows
- [docs/ssot/MANIFEST.yaml](./MANIFEST.yaml) — Concept ownership registry
