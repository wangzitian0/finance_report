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

### deploy.yml

```yaml
Trigger: Manual dispatch only (workflow_dispatch with a required `version_ref` input)
Flow:    resolve release coordinate -> deploy_v2 -> smoke/non-LLM E2E -> AI/OCR regression record
URL:     https://report-staging.zitian.party
```

Staging deploy is manual: it runs only on `workflow_dispatch` and does not
auto-follow main CI. The only operator-supplied release selector is
`version_ref`, and it must be a `vX.Y.Z` release tag. The deploy job resolves
that coordinate through `tools/resolve_release_coordinate.py`, checks out the
tag, derives the pinned infra2 `iac_ref`, never polls or waits for CI inside the
job, and deploys only images that already exist under that release tag. The
resolver validates the exact operator input rather than trimming whitespace, and
fetches only `refs/tags/<version_ref>` without `--force` so moved or rewritten
release tags fail closed.
`deploy.yml` must have promoted the main-CI SHA images to `:vX.Y.Z`
before staging is dispatched. Provider-backed AI/OCR tests run after deploy
health in the same serialized dispatch workflow unit as a right-shifted
regression record, and can also be invoked on demand via
`deploy.yml` when the team wants a blocking diagnostic rerun.

The release process keeps a promote-not-rebuild consistency ladder:
`main CI (:<sha7>) -> deploy.yml (:vX.Y.Z) -> staging deploy_v2
(:vX.Y.Z) -> production deploy_v2 (:vX.Y.Z)`. `deploy.yml` is the only
tag-push promotion path; staging and production both consume the retained release
tag without rebuilding or retagging. The `sha7` tag is fixed to the first 7 hex
characters of the release commit rather than Git's adaptive short length. By
copying single-platform manifests with `imagetools --prefer-index=false`, the
release tag keeps the exact same image digest from main CI through production,
eliminating drift from base images, build-time dependencies, or workflow changes.

The staging deploy gate separates platform rollout from application readiness.
`.github/workflows/deploy.yml` invokes `repo/tools/deploy_v2.py`, which
routes fixed staging/prod deploys through `repo/tools/deploy_primitive.py`.
The primitive updates the allowlisted Dokploy environment, snapshots deployment
ids before mutation, triggers `compose.deploy`, and waits up to 600 seconds for
a new Dokploy deployment record to reach a terminal-good status (`done`,
`success`, or `successful`) before `tools/health_check.sh` starts polling
`/api/health` for the target release tag. `running` only proves Dokploy's worker
has started; it does not prove Docker containers and Traefik routes have
materialized the target tag. No terminal new deployment record means a platform
rollout failure, not an application health timeout.

Production release eligibility depends on the staging run's release-critical
jobs: `Deploy Staging` and `Staging Provider Gate` must succeed for the exact
`Deploy Staging <version_ref>` run. The automatic staging `Staging AI/OCR Gate`
records full-provider regression evidence but does not block production after
deploy health, non-LLM E2E, and provider connectivity have passed.

### release.yml

The production release line is its own manual-dispatch workflow (split out of
`deploy.yml`, #1354). It runs under a `production-release-<version_ref>`
concurrency group with `cancel-in-progress: false` so two production releases
never mutate production concurrently. `deploy.yml` keeps staging deploy and the
tag-push image promotion.

```yaml
Triggers:
  - Manual dispatch: Deploy existing release version_ref to production
  - Manual dry-run:  Validate release prerequisites without deploy (dry_run=true)

Dry-run:    Manual -> Resolve release coordinate -> Verify release evidence -> Release lint -> Verify release image digests -> Skip production mutation
Deploy job: Manual -> Resolve release coordinate -> Verify release evidence -> Verify release image digests -> deploy_v2 -> Health -> Smoke/E2E

URL: https://report.zitian.party
```

---

## Version Release Workflow

```bash
# Create release tag
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3
# -> Triggers deploy.yml
# -> Images: ghcr.io/.../finance_report-{backend,frontend}:v1.2.3

# Deploy to staging (manual)
# -> Actions -> Deploy Staging -> Run workflow -> version_ref=v1.2.3

# Deploy to production (manual, after staging passes)
# -> Actions -> Release -> Run workflow -> version_ref=v1.2.3

# Dry-run production release proof (manual, no production mutation)
# -> Actions -> Release -> Run workflow -> version_ref=v1.2.3, dry_run=true
```

Production app deploys must keep the image tag, Dokploy runtime
`GIT_COMMIT_SHA`, and `/api/health.git_sha` aligned. The release workflow bakes
the tag into backend/frontend image names by manifest-copying main-CI images in
`deploy.yml`. `deploy_v2` then deploys that tag through
`deploy_primitive`, which sets runtime `IMAGE_TAG`, `GIT_COMMIT_SHA`, and a fresh
per-deploy `IAC_CONFIG_HASH` so Dokploy restarts the app even when redeploying
the same tag.
`tools/verify_release_evidence.py` owns the shared production prerequisite
checks for source CI, release-image publication, and exact staging proof;
`tools/verify_release_images.py` owns backend/frontend release digest discovery.
The dry-run and deploy jobs call the same tools so production eligibility logic
does not fork between the two lanes. Both jobs set up the configured
`PYTHON_VERSION` before invoking release-coordinate, evidence, or image-digest
tools so these gates never depend on the runner's default Python alias.
Before mutating production, the release workflow probes the current production
health endpoint and records the pre-deploy version in the deploy context. The
same artifact records deploy-health, smoke, read-only E2E, and failure-domain
fields so a stale-version production failure can be triaged without rerunning
business-correctness gates in production.

Dokploy deploy diagnostics must never print raw API response bodies. The shared
shell helper still redacts raw response bodies for preview/cleanup operations.
The fixed staging/prod deploy path uses the infra2 Python Dokploy client, whose
errors include method, endpoint, status, and reason phrase but not response
bodies, auth headers, or full environment payloads. The fixed path writes only
the allowlisted env keys needed for deploy (`IMAGE_TAG`, `GIT_COMMIT_SHA`,
`IAC_CONFIG_HASH`, `ENV_SUFFIX`, `COMPOSE_PROFILES`, routing, telemetry, and
optional model overrides).

### Stale effective app env failure mode (issue #575)

A Dokploy deploy can report success while the **effective** remote app env /
compose config stays on the previous release: the generated app `.env` keeps the
old `IMAGE_TAG`, `GIT_COMMIT_SHA`, and `IAC_CONFIG_HASH`, so the health gate
reads the stale version for its whole window. Triggering the deploy and seeing
the rollout reach `done` is therefore **not** proof that the requested release is
effective.

To close this gap, after the rollout reaches a terminal-good deployment record
but **before** the long health wait, `deploy_primitive` re-fetches the effective
compose env and verifies `IAC_CONFIG_HASH` with `verify_effective_config_hash`
(secret env values are never echoed):

- **Match** → proceed to the health wait.
- **Stale** → fail fast with diagnostics that name each stale value
  (`expected=... last=...`) before public health starts.

There is no automated force-recreate escape hatch in the fixed staging/prod
release workflow. Recovery is fail-closed: correct the Dokploy/env issue, then
perform a manual rerun of the same `deploy_v2` workflow for the release
`version_ref`. The rerun generates a fresh `IAC_CONFIG_HASH`, snapshots deployment ids before
mutation again, and must pass rollout plus effective-config verification before
health/smoke/E2E run.

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

## Vault Auth (AppRole)

Finance Report is the AppRole **pilot**: its vault-agent authenticates to Vault
with `role_id` + `secret_id` (`VAULT_ROLE_ID` / `VAULT_SECRET_ID`), not the old
periodic `VAULT_APP_TOKEN`. The AppRole secret-id is non-expiring (`secret_id_ttl=0`),
so there is no 7-day token to renew or repair — the agent re-authenticates itself.

| Property | Value |
|----------|-------|
| Auth method | AppRole (`VAULT_ROLE_ID` + `VAULT_SECRET_ID`) |
| Secrets file path | `/secrets/.env` (vault-agent renders to `/vault/secrets`; shared volume mounts into the app as `/secrets`) |
| Staleness threshold | 1 hour (bootloader warning) |

The AppRole creds are owned by infra2 and injected into the Dokploy compose env.
Finance Report deploys must not receive `VAULT_ROOT_TOKEN`. `VAULT_ADDR` is a
non-secret address but **must be present** — a missing `VAULT_ADDR` makes the
vault-agent hang (the deploy preflight fails closed on it).

**(Re)inject app AppRole creds** (e.g. after a rotation, or if a deploy preflight
reports missing `VAULT_ROLE_ID`/`VAULT_SECRET_ID`):

```bash
# From local machine with infra2 repo
cd /path/to/infra2
export VAULT_ROOT_TOKEN="$(op read 'op://Infra2/dexluuvzg5paff3cltmtnlnosm/Token')"
DEPLOY_ENV=staging invoke vault.setup-approle --project=finance_report --service=app --deploy
```

The infra2 task writes the policy + approle role, fetches a fresh role_id/secret_id,
updates the matching Dokploy compose env, and triggers a redeploy (waiting for the
runtime deployment record). For database sidecars use `--service=postgres` or
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
- [observability.md](./observability.md) — App observability runtime contract and OTLP setup
- [runtime-incident-response.md](./runtime-incident-response.md) — Runtime failure triage and stability proof routing
