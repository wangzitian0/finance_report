# Deployment Architecture SSOT

> **SSOT Key**: `deployment`
> **Source of Truth** for deployment workflows, secret injection, and release processes.

*Extracted from [development.md](./development.md) — see also [environments.md](./environments.md) for environment overview.*

---

## Dual-Repository Model

Finance Report uses **two git repositories** for configuration:

| Environment | Configuration Source | Purpose |
|-------------|---------------------|---------|
| **Local/CI** | `/docker-compose.yml` | Development + local/CI service containers |
| **PR preview** | in-runner: `/docker-compose.yml` + `/docker-compose.ci-e2e.yml`; persistent: `/docker-compose.pr-preview.yml` | After successful PR CI: in-runner smoke/E2E (merge authority), then a non-blocking persistent Dokploy preview built from source on the host (no registry push) at `report-pr-<N>.<domain>` |
| **Staging/Production** | `/repo/finance_report/.../compose.yaml` | Production with Vault secrets |

The `/repo/` directory is a git submodule pointing to [`infra2`](https://github.com/wangzitian0/infra2).

**Key implications**:
- Workflows build images and trigger deployments
- Actual deployment config managed in `infra2`
- Env vars for staging/prod stored in HashiCorp Vault
- Backend startup is fail-closed for protected runtimes: public, staging, and production deployments must not use development defaults for `SECRET_KEY`, `DATABASE_URL`, or `S3_SECRET_KEY`.
- Container names include env suffix (e.g., `-staging`)
- Persistent Dokploy PR previews use `/docker-compose.pr-preview.yml`, deployed
  non-blocking after the in-runner E2E gate passes. Dokploy clones the PR branch
  and builds backend/frontend from source on the host (`up -d --build`); no GHCR
  image is pulled or pushed. The preview persists until PR close, then is removed
  by native `compose.delete`.
- **Preview compose project MUST equal Dokploy's `appName`.** `compose.delete`
  tears the stack down with `docker compose down` scoped to the `appName`. The
  preview `up` command therefore passes `-p <appName>` (read back from
  `compose.one`), and the deploy env MUST NOT set `COMPOSE_PROJECT_NAME`.
  Overriding the project (e.g. to `finance_report_pr_<n>`) desyncs `up` from
  `down`: `compose.delete` removes the Dokploy record and on-disk compose
  directory but `down` matches no containers, orphaning the whole stack with
  nothing left to reap it.

---

## Secret Injection Flow

Production deployments use Vault sidecar pattern:

```
1. Dokploy pulls compose.yaml from infra2
2. vault-agent sidecar starts → renders /secrets/.env
3. Backend waits for secrets (CHECKPOINT-1)
4. Alembic runs migrations (CHECKPOINT-2)
5. Uvicorn starts application (CHECKPOINT-3)
```

Health check timeout (6 min) accounts for this entire flow.

### Secret Contract (cross-repo seam)

One contract ties the three repos together; each owns only its part:

| Repo | Owns | Knows about others |
|------|------|--------------------|
| **finance_report** (app) | `apps/backend/src/config.py` declares every variable and its default; `apps/backend/src/boot.py` enforces which secrets must be real at boot. | Nothing at build time; reads `os.environ` regardless of source. |
| **dev_env** (local tooling) | Injects local secrets from 1Password (no plaintext at rest); source-agnostic. | Nothing about app schemas. |
| **infra2** (`repo/`) | Vault `secrets.ctmpl` — supplies the deployed values. | The env vars a deployed app requires. |

Consistency is **not** enforced by cross-repo CI gates. It is enforced where it
matters: the app **fails loudly at boot** in a *protected* runtime.
`apps/backend/src/boot.py` (`Bootloader._check_static_config`, the single source
of truth for environment validation) treats a runtime as protected when the
environment is `staging`/`production`, is **not** one of the local environments
(`development`, `test`, `ci`), or the app is served from a public (non-localhost
`https://`) `NEXT_PUBLIC_APP_URL`. In a protected runtime it rejects a
missing/short/default `SECRET_KEY`, a default `DATABASE_URL`, or a default
`S3_SECRET_KEY`. Startup runs it via `apps/backend/src/main.py` →
`await Bootloader.validate(BootMode.CRITICAL)`, which `sys.exit(1)`s on failure
(the deploy readiness gate catches it). Local/CI keep convenience defaults.
Proven by AC1.10.1.

---

## CI Deployment Workflows

### ci.yml (PR/push)

```
Trigger: PR or push to main
Steps:   install → lint → test
DB:      GitHub services (ephemeral)
Smoke:   ❌ Not run (unit tests only)
```

### staging-deploy.yml

```yaml
Trigger: Successful push CI workflow_run on main or manual dispatch
Flow:    promote SHA images -> deploy -> smoke/non-LLM E2E -> AI/OCR gate
URL:     https://report-staging.zitian.party
```

Normal staging deploys reuse SHA-tagged backend and frontend images built by the
matching successful `push` `CI` workflow on `main`. The deploy job checks out the CI
`workflow_run.head_sha`, so it no longer spends staging runner time polling for
CI completion. If a SHA image is missing, staging falls back to building only
the missing image before promotion. Provider-backed AI/OCR tests run after
deploy health in the same serialized post-merge workflow unit.
Non-`push`, failed, cancelled, timed-out, or non-main CI workflow runs write a
skipped summary before FIFO wait, image promotion, Dokploy rollout, smoke tests,
or AI/OCR validation can run.

The production release workflow strictly promotes the staging-validated image digest to the release version tag (`vX.Y.Z`) instead of rebuilding from source. This creates a promote-not-rebuild consistency ladder: `pr (SHA image) → staging (promotes SHA to staging tag, validates digest) → prod (promotes staging-validated SHA to version tag)`. By keeping the exact same image digest across all three environments, we eliminate drift from base images, build-time dependencies, or workflow changes, ensuring that production only runs artifacts that have been fully tested and validated.

The staging deploy gate separates platform rollout from application readiness.
`tools/dokploy_deploy.sh` updates the allowlisted Dokploy environment, triggers
`compose.deploy`, then waits up to 600 seconds for a new Dokploy deployment
record to reach `done` before `tools/health_check.sh` starts polling
`/api/health` for the target SHA. `running` only proves Dokploy's worker has
started; it does not prove Docker containers and Traefik routes have
materialized the target SHA. A deployment that reuses an existing deployment id
and advances it to `done` is accepted as ready state; if no record appears and
no existing record advances, a missing or unfinished deployment record after
that worker-queue window is a platform rollout failure, not an application
health timeout.

### production-release.yml

```yaml
Triggers:
  - Tag push (v*.*.*): Promote staging-validated images
  - Manual dispatch:   Deploy to production
  - Manual dry-run:    Validate release prerequisites without deploy

Build job:  Tag → Verify successful main CI for SHA → Verify successful staging run → Release lint → Promote staging-validated SHA images to version tag → Skip rebuild
Dry-run:    Manual → Verify successful main CI for SHA → Verify successful staging run → Release lint → Verify SHA images exist and fetch digests → Skip promotion and rebuild
Deploy job: Verify images → Deploy → Health (4min) → Smoke test

URL: https://report.zitian.party
```

---

## Version Release Workflow

```bash
# Create release tag
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
# → Triggers production-release.yml (build job)
# → Images: ghcr.io/.../finance_report-{backend,frontend}:v1.2.3

# Deploy to production (manual)
# → Actions → Production Release → Run workflow → Select v1.2.3

# Dry-run production release proof (manual, no production mutation)
# → Actions → Production Release → Run workflow → dry_run=true
```

Production app deploys must keep the image tag, Dokploy runtime
`GIT_COMMIT_SHA`, and `/api/health.git_sha` aligned. The release workflow bakes
the tag into backend images, and `tools/dokploy_deploy.sh` refreshes
`IAC_CONFIG_HASH` on every deploy attempt so Dokploy restarts the app even when
redeploying the same tag.
Before mutating production, the release workflow probes the current production
health endpoint and records the pre-deploy version in the deploy context. The
same artifact records deploy-health, smoke, read-only E2E, and failure-domain
fields so a stale-version production failure can be triaged without rerunning
business-correctness gates in production.

Dokploy deploy diagnostics must never print raw API response bodies. The shared
deploy helper reports only endpoint, HTTP status, safe message fields, and an
allowlisted effective environment diff for `IMAGE_TAG`, `GIT_COMMIT_SHA`,
`IAC_CONFIG_HASH`, `ENV_SUFFIX`, and `COMPOSE_PROFILES`.

### Stale effective app env failure mode (issue #575)

A Dokploy deploy can report success while the **effective** remote app env /
compose config stays on the previous release: the generated app `.env` keeps the
old `IMAGE_TAG`, `GIT_COMMIT_SHA`, and `IAC_CONFIG_HASH`, so the health gate
reads the stale version for its whole window. Triggering the deploy and seeing
the rollout reach `done` is therefore **not** proof that the requested release is
effective.

To close this gap, after the rollout reaches `done` but **before** the long
health wait, `tools/dokploy_deploy.sh` re-fetches `compose.one` and verifies the
**effective** remote app env against the requested release via
`verify_effective_remote_app_env` (allowlisted `IMAGE_TAG`, `GIT_COMMIT_SHA`,
`IAC_CONFIG_HASH`; secret env values are never echoed):

- **Match** → proceed to the health wait.
- **Stale** → fail fast with diagnostics that name each stale value
  (`expected=… actual=…`), and attempt one **guarded automated recovery** path
  before failing the deploy.

The automated recovery is `force_recreate_stateless_app`, gated behind the
explicit `DOKPLOY_ALLOW_FORCE_RECREATE=true` opt-in. It refreshes the release
token with a fresh `IAC_CONFIG_HASH` (forcing Dokploy to recreate the stateless
app containers even for an unchanged image tag), re-pushes the corrected env, and
forces a `compose.redeploy`. The recreate also resolves the fixed
`container_name` (`finance_report-{backend,frontend}${ENV_SUFFIX}`) conflict by
replacing the stale stateless containers; postgres/redis are never touched. The
deploy then re-verifies the effective env and fails the release if it is still
stale. This replaces the previous manual SSH + stateless container recreate
recovery.

Dokploy API and CLI usage should stay minimal and state-oriented. Use whichever
surface exposes the required operation, then prove correctness by comparing the
effective runtime state against the requested allowlist; do not log full API
responses or full environment templates.

VPS disk hygiene is not a GitHub Actions SSH responsibility. Dokploy owns the
operational schedule through a `dokploy-server` Schedule Job managed by
`tools/vps_host_hygiene.py --ensure-dokploy-schedule`. The `dokploy-server` type
is mandatory: the legacy `server` type with a null `serverId` is accepted by
`schedule.create` but never executes the command — a silent no-op that
previously let orphaned resources accumulate. The job is **generic-only**: it
prunes aged stopped non-preview containers, build cache, unused images, all
unused Docker networks, oversized Docker json logs, and vacuums the systemd
journal. Unused Docker networks are not age-gated because Docker's predefined
address pools can be exhausted by orphan networks before disk retention
thresholds are reached; Docker does not remove networks attached to running
containers. PR preview environments are reaped natively by Dokploy
`compose.delete` (reliable since Dokploy v0.29.x), not by host hygiene; the
preview container-name pattern is retained only to *exclude* Dokploy-owned
preview containers from generic stopped-container pruning. PR preview workflows
only create, update, deploy, delete, and reconcile Dokploy compose resources.

PR preview no longer creates PR-scoped GHCR images. Immediate PR-close cleanup
therefore does not delete image tags. The scheduled cleanup still prunes legacy
closed-PR `pr-<number>-<sha>` tags older than 14 days while keeping tags for
currently open PRs.

Install or update the Dokploy host hygiene schedule with:

```bash
python tools/vps_host_hygiene.py \
  --ensure-dokploy-schedule \
  --api-url https://cloud.zitian.party/api \
  --api-key "$DOKPLOY_API_KEY" \
  --server-id null
```

For the local Dokploy host the schedule is `dokploy-server`-scoped and needs no
real server id; pass `--server-id null` (it normalizes to a null `serverId`).
Use `--print-dokploy-schedule-payload --server-id null` to inspect the exact
payload without mutating Dokploy.

**Hotfix flow**:
```bash
git checkout -b hotfix/bug v1.2.3
git cherry-pick abc123
git tag -a v1.2.4 -m "Hotfix: critical bug"
git push origin v1.2.4
# → Build automatically, deploy manually
```

---

## Database Migrations

Migrations run automatically on container startup via the entrypoint:

```yaml
# In infra2 compose.yaml
entrypoint:
  - sh
  - -c
  - |
    cd /app && export PYTHONPATH=/app
    # Wait for secrets...
    alembic upgrade head  # ← Runs migrations
    exec uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Before deploying schema changes**:
1. Test migration locally with `docker-compose.yml`
2. Ensure migration is backward-compatible (for rollback)
3. Run `python tools/check_migration_risk.py` and review
   `docs/ssot/migration-risk.yaml`
4. Use the declared risk level to choose the release proof:
   - **low**: PR Alembic contract is usually enough
   - **medium**: require staging deploy proof for the compatibility-sensitive path
   - **high**: require staging evidence plus production preflight and rollback/expand-contract notes
   - **critical**: require all high-risk proof plus explicit destructive-change confirmation

This process does not guarantee production data migration safety. Staging should
catch most migration problems, while production-only residual risk is controlled
with backups, idempotent backfills, feature flags, preflight queries, and
post-deploy detectors.

---

## Runtime Incident Response

Runtime failure triage is owned by
[runtime-incident-response.md](./runtime-incident-response.md). This deployment
SSOT owns deploy architecture, release flow, Vault token boundaries, and
Dokploy safety rules. Use the runtime incident SSOT for 502/503 responses,
route failures, stale deployed versions, missing logs/alerts, expired-secret
symptoms, and flapping recovery proof.

---

## Vault Token Lifecycle

| Property | Value |
|----------|-------|
| Token period | 168 hours (7 days), renewable by vault-agent |
| Secrets file path | `/secrets/.env` |
| Staleness threshold | 1 hour (bootloader warning) |

`VAULT_APP_TOKEN` is owned by infra2. Finance Report deploys only preflight the
Dokploy token and must not receive `VAULT_ROOT_TOKEN`.

**Repair app token** (when expired):

```bash
# From local machine with infra2 repo
cd /path/to/infra2
export VAULT_ROOT_TOKEN="$(op read 'op://Infra2/dexluuvzg5paff3cltmtnlnosm/Token')"
DEPLOY_ENV=staging invoke vault.setup-tokens --project=finance_report --service=app
```

The infra2 task updates the matching Dokploy compose env, triggers redeploy,
tracks the new accessor, and revokes the previous accessor after a successful
Dokploy update. For database sidecars use `--service=postgres` or
`--service=redis`.

**Monitoring**: Bootloader `_check_vault_secrets()` runs in FULL mode and reports:
1. Missing secrets file → Warning with regeneration instructions
2. Stale secrets file (>1 hour old) → Warning
3. Fresh secrets file → OK

---

## Cross-Repo Synchronization

If a change requires new environment variables or changes to `docker-compose.yml` labels/configs for production:

1. Create a branch in `repo/` submodule
2. Commit changes to `repo/finance_report/finance_report/10.app/`
3. Push and create a PR in `infra2`
4. Once merged, update the submodule pointer in the main repo PR

---

## Related

- [environments.md](./environments.md) — Six environment overview and naming
- [development.md](./development.md) — Local development and Moon commands
- [ci-cd.md](./ci-cd.md) — CI job structure and test strategy
- [observability.md](./observability.md) — App observability runtime contract and SigNoz OTLP setup
- [runtime-incident-response.md](./runtime-incident-response.md) — Runtime failure triage and stability proof routing
