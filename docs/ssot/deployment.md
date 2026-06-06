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
| **PR preview** | `/docker-compose.pr-preview.yml` | Dokploy GitHub-source PR previews using CI-built images only; services are not profile-gated |
| **Staging/Production** | `/repo/finance_report/.../compose.yaml` | Production with Vault secrets |

The `/repo/` directory is a git submodule pointing to [`infra2`](https://github.com/wangzitian0/infra2).

**Key implications**:
- Workflows build images and trigger deployments
- Actual deployment config managed in `infra2`
- Env vars for staging/prod stored in HashiCorp Vault
- Backend startup is fail-closed for protected runtimes: public, staging, and production deployments must not use development defaults for `SECRET_KEY`, `DATABASE_URL`, or `S3_SECRET_KEY`.
- Container names include env suffix (e.g., `-staging`)
- PR previews must set explicit commit-scoped internal service URLs such as `S3_ENDPOINT=http://finance-report-minio-pr-$PR_NUMBER-$COMMIT_SLUG:9000`; nested compose env expansion is not portable.

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

### production-release.yml

```yaml
Triggers:
  - Tag push (v*.*.*): Build release images
  - Manual dispatch:   Deploy to production
  - Manual dry-run:    Validate release prerequisites without deploy

Build job:  Tag → Verify successful main CI for SHA → Release lint → Build backend + frontend → Push to GHCR
Dry-run:    Manual → Verify successful main CI for SHA → Release lint → Build production images with push=false → Skip Dokploy
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

Dokploy deploy diagnostics must never print raw API response bodies. The shared
deploy helper reports only endpoint, HTTP status, safe message fields, and an
allowlisted effective environment diff for `IMAGE_TAG`, `GIT_COMMIT_SHA`,
`IAC_CONFIG_HASH`, `ENV_SUFFIX`, and `COMPOSE_PROFILES`.

Dokploy API and CLI usage should stay minimal and state-oriented. Use whichever
surface exposes the required operation, then prove correctness by comparing the
effective runtime state against the requested allowlist; do not log full API
responses or full environment templates.

VPS disk hygiene is not a GitHub Actions SSH responsibility. Dokploy owns the
operational schedule through a `server` Schedule Job managed by
`tools/vps_host_hygiene.py --ensure-dokploy-schedule`. The job prunes generic
Docker and journal garbage, and keeps PR preview Docker resources created within
the last 3 days or belonging to the most recent 3 PR numbers. PR preview
workflows only create, update, deploy, delete, and reconcile Dokploy compose
resources.

Install or update the Dokploy host hygiene schedule with:

```bash
python tools/vps_host_hygiene.py \
  --ensure-dokploy-schedule \
  --api-url https://cloud.zitian.party/api \
  --api-key "$DOKPLOY_API_KEY" \
  --server-id "$DOKPLOY_SERVER_ID"
```

Use `--print-dokploy-schedule-payload --server-id "$DOKPLOY_SERVER_ID"` to
inspect the exact payload without mutating Dokploy. The default retention policy
is `--pr-preview-max-age-days 3 --pr-preview-keep-recent 3`.

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
3. Consider: existing data, indexes, constraints

---

## Deployment Failures

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Stuck "Waiting for secrets" | Vault token expired | `DEPLOY_ENV=staging invoke vault.setup-tokens --project=finance_report --service=app` from infra2 |
| 6 min timeout | Migration failed | Check SigNoz for CHECKPOINT-2 errors |
| "Image not found" | Tag not built | `git push origin v1.2.3` to trigger build |
| 502 Bad Gateway | Backend crashed | Check CHECKPOINT-3 in SigNoz logs |

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
- [observability.md](./observability.md) — SigNoz logs for debugging deployments
