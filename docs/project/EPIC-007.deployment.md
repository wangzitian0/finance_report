# EPIC-007: Production Deployment

> **Status**: ✅ Complete  
> **Vision Anchor**: `decision-7-tech-stack`  
> **Phase**: 0 (Infrastructure)  
> **Duration**: 1 week  
> **Dependencies**: EPIC-001, EPIC-002, EPIC-003  

---

## 🎯 Objective

Deploy Finance Report application to production environment using Dokploy + vault-init pattern, with independent PostgreSQL and Redis instances.

**Target Domain**: `report.${INTERNAL_DOMAIN}` (e.g., `report.zitian.party`)

**Core Architecture**:
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

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Isolation | Independent PG/Redis, shared MinIO, vault-init for secrets |
| 💻 **Developer** | CI/CD | Docker build from apps/, compose orchestration |
| 🔒 **Security** | Secrets | Vault KV v2, no disk persistence, tmpfs for secrets |
| 🌐 **Network** | Domain | Single domain for FE+BE, Traefik routing |
| 📋 **PM** | Scope | Deploy EPIC 1-3 features first |

---

## ✅ Task Checklist

### Phase 1: Infrastructure Setup

- [x] Add infra2 as submodule at `repo/`
- [x] Create `repo/finance_report/finance_report/` directory structure
- [x] Create README.md for finance_report layer

### Phase 2: Database Layer (01.postgres)

- [x] `compose.yaml` - PostgreSQL 16 with vault-agent sidecar
- [x] `deploy.py` - PostgresDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for postgres
- [x] `secrets.ctmpl` - Secrets template
- [x] `README.md` - Documentation

### Phase 3: Cache Layer (02.redis)

- [x] `compose.yaml` - Redis with vault-agent sidecar
- [x] `deploy.py` - RedisDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for redis
- [x] `secrets.ctmpl` - Secrets template
- [x] `README.md` - Documentation

### Phase 4: Application Layer (10.app)

- [x] `compose.yaml` - Backend + Frontend with vault-agent sidecar
- [x] `deploy.py` - AppDeployer class
- [x] `shared_tasks.py` - Health check tasks
- [x] `vault-agent.hcl` - Vault agent configuration
- [x] `vault-policy.hcl` - Vault policy for app
- [x] `secrets.ctmpl` - Secrets template (DATABASE_URL, REDIS_URL, S3_*, ZAI_API_KEY)
- [x] `README.md` - Documentation
- [x] Traefik labels for `report.${INTERNAL_DOMAIN}`

### Phase 5: Vault Secrets Setup

- [x] Write secrets to Vault:
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
    - ZAI_API_KEY
  ```
- [x] Provision service AppRole creds via `invoke vault.setup-approle`

### Phase 6: Deployment & Verification

- [x] Deploy postgres (historical initial provision; current deploy path is `deploy_v2`)
- [x] Deploy redis (historical initial provision; current deploy path is `deploy_v2`)
- [x] Deploy app (historical initial provision; current deploy path is `deploy_v2`)
- [x] Verify health checks
- [x] Test `https://report.${INTERNAL_DOMAIN}`

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/infra/` and `tools/smoke_test.sh`

### AC7.1: Infrastructure Setup

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.1.1 | Infra2 submodule exists | Manual verification | Git | P0 |
| AC7.1.2 | Finance_report directory structure | Manual verification | `repo/finance_report/` | P0 |
| AC7.1.3 | README documentation exists | Manual verification | `repo/finance_report/finance_report/README.md` | P0 |

### AC7.2: Database Layer (PostgreSQL)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.2.1 | PostgreSQL container configured | Manual verification | `repo/finance_report/finance_report/01.postgres/compose.yaml` | P0 |
| AC7.2.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/01.postgres/compose.yaml` | P0 |
| AC7.2.3 | Vault policy for postgres | Manual verification | `repo/finance_report/finance_report/01.postgres/vault-policy.hcl` | P0 |
| AC7.2.4 | Secrets template for postgres | Manual verification | `repo/finance_report/finance_report/01.postgres/secrets.ctmpl` | P0 |
| AC7.2.5 | PostgresDeployer class exists | Manual verification | `repo/finance_report/finance_report/01.postgres/deploy.py` | P0 |

### AC7.3: Cache Layer (Redis)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.3.1 | Redis container configured | Manual verification | `repo/finance_report/finance_report/02.redis/compose.yaml` | P0 |
| AC7.3.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/02.redis/compose.yaml` | P0 |
| AC7.3.3 | Vault policy for redis | Manual verification | `repo/finance_report/finance_report/02.redis/vault-policy.hcl` | P0 |
| AC7.3.4 | Secrets template for redis | Manual verification | `repo/finance_report/finance_report/02.redis/secrets.ctmpl` | P0 |
| AC7.3.5 | RedisDeployer class exists | Manual verification | `repo/finance_report/finance_report/02.redis/deploy.py` | P0 |

### AC7.4: Application Layer (Backend + Frontend)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.4.1 | App container configured | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.2 | Vault-agent sidecar present | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.3 | Vault policy for app | Manual verification | `repo/finance_report/finance_report/10.app/vault-policy.hcl` | P0 |
| AC7.4.4 | Secrets template for app | Manual verification | `repo/finance_report/finance_report/10.app/secrets.ctmpl` | P0 |
| AC7.4.5 | Traefik labels for domain | Manual verification | `repo/finance_report/finance_report/10.app/compose.yaml` | P0 |
| AC7.4.6 | AppDeployer class exists | Manual verification | `repo/finance_report/finance_report/10.app/deploy.py` | P0 |

### AC7.5: Vault Secrets Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.5.1 | DATABASE_URL in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.2 | REDIS_URL in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.3 | S3_* keys in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.4 | ZAI_API_KEY in Vault | Manual verification | Vault secret path | P0 |
| AC7.5.5 | Vault AppRole creds provisioned | Manual verification | `invoke vault.setup-approle` | P0 |

### AC7.6: Backend Configuration & Secrets Sync

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.6.1 | Config syncs with .env.example | `TestConfigContract.test_config_sync_with_env_example` | `infra/test_config_contract.py` | P0 |
| AC7.6.2 | Required secrets documented | Manual verification | `.env.example` | P0 |

### AC7.7: Health Checks

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.7.1 | Health endpoint returns 200 | `test_health_when_all_services_healthy()` | `infra/test_main.py` | P0 |
| AC7.7.2 | Health check with services down | `test_health_returns_503_on_database_failure()`, `test_health_fails_when_redis_configured_but_unavailable()`, `test_health_returns_503_on_s3_failure()` | `infra/test_main.py` | P0 |

### AC7.8: Docker & CI Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.8.1 | Moon local CLI contract is versioned without PR CI bootstrap | `test_moon_cli_static_contract_available()` | `infra/test_ci_config.py` | P0 |
| AC7.8.2 | Docker compose integrity | `test_docker_compose_integrity()` | `infra/test_ci_config.py` | P0 |
| AC7.8.3 | Moon project graph contract is declared in repo config | `test_moon_project_graph_static_contract()` | `infra/test_ci_config.py` | P0 |

### AC7.9: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.9.1 | PostgreSQL healthy (manual) | `invoke finance_report.postgres.status` | Infra2 commands | P0 |
| AC7.9.2 | Redis healthy (manual) | `invoke finance_report.redis.status` | Infra2 commands | P0 |
| AC7.9.3 | App healthy (manual) | `invoke finance_report.app.status` | Infra2 commands | P0 |
| AC7.9.4 | Domain accessible (manual) | `curl https://report.${INTERNAL_DOMAIN}` | Smoke tests | P0 |
| AC7.9.5 | API functional (manual) | `curl https://report.${INTERNAL_DOMAIN}/api/health` | Smoke tests | P0 |
| AC7.9.6 | Secrets in Vault (manual) | No secrets in Dokploy env vars | Manual verification | P0 |
| AC7.9.7 | Backend health endpoint | `test_health_when_all_services_healthy()` | `infra/test_main.py` | P0 |
| AC7.9.8 | Config contract validation | `TestConfigContract` class | `infra/test_config_contract.py` | P0 |

### AC7.10: Promote and Release Pipeline Integrity

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.10.1 | `deploy.yml` promotes the staging-validated image to `vX.Y.Z` instead of rebuilding from source | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.2 | Release fails closed if no staging-validated SHA image exists or if digests differ | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.3 | Workflow summary records released commit, source CI run, promoted image digest, and no rebuild | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.4 | Deployment and CI SSOTs document the promote-not-rebuild consistency ladder | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |
| AC7.10.5 | Retain `workflow_dispatch` dry-run to prove the release/promote path without mutating production | `test_AC7_10_production_release_promotes_not_rebuilds` | `tests/tooling/test_post_merge_e2e_gates.py` | P0 |

### AC7.11: Database Migration Risk Governance

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.11.1 | Backend Alembic migrations are covered by a machine-readable migration risk manifest | `test_AC7_11_1_migration_risk_manifest_covers_backend_migrations` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.2 | High and critical migration risk entries require release proof notes for staging, production preflight, and rollback/expand-contract strategy | `test_AC7_11_2_high_and_critical_migrations_require_release_proof` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.3 | Destructive upgrade operations cannot be classified below critical risk | `test_AC7_11_3_destructive_migrations_must_be_classified_critical` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.4 | CI lint and production release dry-run execute the migration risk contract and publish release context | `test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract` | `tests/tooling/test_migration_risk_contract.py` | P0 |
| AC7.11.5 | Risk is auto-classified from each migration's `upgrade()` body (destructive→critical, data-mutation→high, compatibility-sensitive→medium, else low); low/medium migrations need no manifest entry, while auto-classified high/critical migrations require an explicit release-proof entry | `test_AC7_11_5_low_and_medium_migrations_are_auto_classified` | `tests/tooling/test_migration_risk_contract.py` | P0 |

### AC7.12: Delivery App/Infra-boundary calibration (#876)

> Framework doc-of-record lives in issue #876 (G1–P3). This table tracks only ACs that already have a test; the rest land with their implementing PRs.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.12.3 | The staging/prod deploy compose (infra2 `10.app/compose.yaml`) cannot local-build the app services (no `build:`, `pull_policy: always`), and the postgres/redis data dirs are bind-mounted via `${DATA_PATH}` (not a named volume Dokploy wipes on redeploy) | `test_AC7_12_3_deploy_compose_pull_not_build`, `test_AC7_12_3_data_dirs_survive_redeploy` | `tests/tooling/test_deploy_compose_contract.py` | P0 |
| AC7.12.4 | App publishes the artifact: `ci.yml` pushes `:<sha>` for `main` and release-branch (`release/**`) commits, `workflow_dispatch` can publish an arbitrary sha on demand, and the persistent Dokploy preview is on-demand only (`deploy-preview` runs via `workflow_dispatch`, not per-PR auto) while the in-runner `e2e` gate stays automatic | `test_AC7_12_4_release_branches_trigger_the_publish_workflow`, `test_AC7_12_4_image_push_publishes_for_main_release_and_dispatch`, `test_AC7_12_4_persistent_preview_is_on_demand_not_per_pr` | `tests/tooling/test_publish_only_contract.py` | P1 |
| AC7.12.6 | SSOT (`environments.md`) defines the derived data-lane contract for `deploy_v2(service, type, version_ref, iac_ref)`, the current data sources/defaults (empty / staging / anonymized prod snapshot / prod), and the four data red lines (RL-DATA-1..4): a PR sha never runs on prod data; prod data is anonymized before leaving prod; non-prod object storage holds no real uploads; a backup is not an anonymized snapshot | `test_AC7_12_6_environments_define_data_axis_and_red_lines`, `test_AC7_12_6_deploy_v2_data_lane_is_derived_not_public_axis` | `tests/tooling/test_data_red_lines_contract.py` | P1 |
| AC7.12.8 | The published `:<sha>` front-end image is environment-independent (same-origin `/api`, no environment domain baked in); a contract test fails if a concrete environment domain appears in the published image | `test_AC7_12_8_published_frontend_image_has_no_baked_env_domain` | `tests/tooling/test_frontend_same_origin_contract.py` | P0 |

### AC7.13: Preview rollout proof & half-update safety (#756, #758)

> The PR preview lifecycle (`tools/_lib/dev/pr_preview_lifecycle.py`) must fail
> fast when Dokploy never creates a new deployment record (#756) and must never
> leave a silently half-updated compose on a deploy/rollout failure (#758).

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.13.1 | A `composeStatus=done` rollout with no new deployment record for the requested SHA fails fast with the classified `DokployNoNewDeploymentRecord` error (`platform_failure_domain=dokploy-worker-or-deployment-record`) instead of proceeding to commit-scoped readiness against stale records | `test_AC7_13_1_no_new_deployment_record_raises_classified_subclass` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC7.13.2 | Rollout diagnostics distinguish "no new deployment created" from "new deployment created but route not ready", and effective-env reconciliation flags stale non-allowlisted keys by name without leaking secret values | `test_AC7_13_2_env_reconciliation_rejects_stale_non_allowlisted_keys` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC7.13.3 | `update_compose_env` reconciles the whole requested env against the effective remote env and fails fast when a stale non-allowlisted key diverges | `test_AC7_13_3_update_compose_env_fails_fast_on_stale_keys` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC7.13.4 | On deploy/rollout failure the lifecycle rolls back to last-known-good source/env or marks the record safe-to-reconcile, recording which mutation step (source/env/deploy/rollout) it was left at — never a silent half-update | `test_AC7_13_4_mutate_then_fail_marks_state_and_records_step` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |
| AC7.13.5 | The CI/CD SSOT documents both the no-new-deployment fail-fast mode and the half-update rollback / safe-to-reconcile recovery path | `test_AC7_13_5_ci_cd_docs_describe_failure_modes` | `tests/tooling/test_pr_preview_lifecycle.py` | P0 |

### AC7.14: Effective Production App Env Verification (#575)

> The production deploy must verify the effective remote app env (`IMAGE_TAG`,
> `GIT_COMMIT_SHA`, `IAC_CONFIG_HASH`) before the long health wait and fail fast
> on stale Dokploy config. The fixed staging/prod path is now infra2
> `deploy_v2` / `deploy_primitive`, not the retired app-side bash deploy script.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.14.1 | The fixed staging/prod deploy path verifies the effective remote app config (`IAC_CONFIG_HASH`) after Dokploy rollout and before the public health wait; a matching effective config proceeds | `test_AC7_14_1_verify_runs_after_rollout_and_before_health` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |
| AC7.14.2 | If Dokploy reports success but the effective app env / compose config is stale, the deploy fails fast with diagnostics that name the stale `IAC_CONFIG_HASH` without echoing secrets | `test_AC7_14_2_stale_effective_config_fails_fast_without_secret_echo` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |
| AC7.14.3 | Stale effective config is fail-closed on the unified deploy_v2 path; the retired force-recreate escape hatch is absent from production release, and recovery is a manual rerun after the Dokploy/env issue is corrected | `test_AC7_14_3_no_force_recreate_escape_hatch_remains` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |
| AC7.14.4 | `repo/tools/deploy_primitive.py` and infra2 primitive tests have contract coverage for rollout wait, Vault preflight, effective config verification, and forced per-deploy `IAC_CONFIG_HASH` refresh | `test_AC7_14_1_verify_runs_after_rollout_and_before_health`, `test_AC7_14_2_stale_effective_config_fails_fast_without_secret_echo`, `test_AC7_14_6_rollout_baseline_is_snapshotted_before_mutation` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |
| AC7.14.5 | Production deployment docs describe the stale effective-config failure mode and deploy_v2 manual rerun recovery path | `test_AC7_14_5_deployment_doc_describes_effective_config_failure_and_recovery` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |
| AC7.14.6 | The rollout-wait baseline (`before_ids`) is snapshotted before `update_compose_env` / `deploy_compose`, so fast new deployments are detected as new records and no-op deploys fail before readiness | `test_AC7_14_6_rollout_baseline_is_snapshotted_before_mutation` | `tests/tooling/test_issue_575_effective_env_verify.py` | P0 |

### AC7.15: CI/Deploy Workflow Contract vs SSOT (#531)

> Prose in `docs/ssot/ci-cd.md`, `deployment.md`, and `environments.md`, plus the
> issue templates, must not drift from the live `.github/workflows/*.yml` job ids,
> triggers, and the repository label taxonomy. `tools/check_workflow_contract.py`
> is the mechanical guard; static docs must not duplicate mutable live run status.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.15.1 | The CI/deploy SSOT references the live workflow job ids and triggers through a checked contract (not stale prose), and CI lint runs `tools/check_workflow_contract.py` | `test_AC7_15_1_real_repo_passes_the_workflow_contract`, `test_AC7_15_1_ci_workflow_wires_the_workflow_contract_gate` | `tests/tooling/test_workflow_contract.py` | P0 |
| AC7.15.2 | Issue templates use only labels that exist in the current repository taxonomy (stale `infra`/`feature` and any unknown label fail) | `test_AC7_15_2_stale_issue_template_label_fails`, `test_AC7_15_2_unknown_issue_template_label_fails` | `tests/tooling/test_workflow_contract.py` | P0 |
| AC7.15.3 | The contract FAILS when a workflow job id, trigger, or issue-template label drifts from the documented standard (e.g. `classify-changes` prose, a `push` trigger re-added to the `deploy.yml` staging target, or a renamed classifier job) | `test_AC7_15_3_stale_ci_classifier_job_name_fails`, `test_AC7_15_3_stale_staging_push_trigger_prose_fails`, `test_AC7_15_3_staging_push_trigger_in_workflow_fails`, `test_AC7_15_3_renamed_classifier_job_in_workflow_fails`, `test_AC7_15_3_main_cli_returns_contract_result` | `tests/tooling/test_workflow_contract.py` | P0 |

### AC7.16: Transient Toolchain-Download Retry in the Staging Deploy Path (#412)

> The staging deploy path still runs shell steps that download tools over the
> network (E2E test deps + Playwright browsers via the shared
> `setup-e2e-tests` composite, and the deploy_v2 dependency install). These are
> genuine transient-failure surfaces (timeout/504) with no bounded retry. They
> must retry with bounded exponential backoff (mirroring the existing
> "AI Provider Connectivity Smoke" idiom) and keep the original external error
> visible on exhaustion. Application deploy/test execution steps stay
> fail-fast — only the toolchain download commands are wrapped. `setup-uv` /
> `setup-python` action steps already retry internally and are left untouched.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.16.1 | The shared E2E toolchain-setup composite (`setup-e2e-tests`) retries transient dependency/browser download failures (`uv pip install`, `playwright install`) with bounded exponential backoff and keeps the original external error visible on exhaustion | `test_AC7_16_1_setup_e2e_composite_retries_toolchain_downloads`, `test_AC7_16_1_setup_e2e_composite_does_not_wrap_test_execution` | `tests/tooling/test_staging_toolchain_retry.py` | P0 |
| AC7.16.2 | The staging deploy_v2 dependency install retries transient download failures with bounded exponential backoff; application deploy/test steps remain fail-fast (not wrapped in retry) | `test_AC7_16_2_staging_deploy_v2_dependency_install_retries`, `test_AC7_16_2_staging_deploy_and_e2e_steps_stay_fail_fast` | `tests/tooling/test_staging_toolchain_retry.py` | P0 |

### AC7.17: Smoke Gate Asserts Only Real Public Frontend Routes (#411)

> The deploy-smoke gate (`tools/_lib/shell/smoke_test.sh`) runs in the staging /
> PR-preview health gate. Every page route it asserts must correspond to a real,
> publicly reachable Next.js route under `apps/frontend/src/app` — a smoke check
> for a non-existent path (e.g. `/dashboard`, which 404s) makes the gate either
> flap or pass for the wrong reason. The smoke script must not assert a page path
> that has no `page.tsx` and must not assert a path that 401s for anonymous
> requests.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.17.1 | Every page route the smoke gate asserts (`check_endpoint "...Page" "$BASE_URL/<route>"`) maps to a real public Next.js route that exists under `apps/frontend/src/app` (route-group folders excluded); the removed `/dashboard` path (no `page.tsx`) is not asserted | `test_AC7_17_1_smoke_asserts_only_existing_public_frontend_routes`, `test_AC7_17_1_smoke_does_not_assert_nonexistent_dashboard_route` | `tests/tooling/test_smoke_routes_contract.py` | P0 |

### AC7.18: Build-Time Secret-Scan Gate on the Image Build Context (#1277)

> The lint job already content-scans the working tree with gitleaks. The image
> build is a second, independent surface: a secret can enter the Docker build
> context (`./apps/<component>`) and be baked into a published `:<sha>` image.
> The `container-images` job must run a fail-closed gitleaks scan over the build
> context BEFORE `docker/build-push-action`, so a secret in the context fails the
> build and the finding stays visible in the job logs (redacted value).

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.18.1 | The CI `container-images` job runs a gitleaks secret scan over the per-component build context before the image build step, fails closed on detection (`--exit-code 1` / `--no-git`), and keeps the finding visible in logs (`--redact`, no `--no-banner`-only silent pass) | `test_AC7_18_1_container_images_job_has_build_context_secret_scan`, `test_AC7_18_1_build_secret_scan_is_fail_closed_before_build` | `tests/tooling/test_build_secret_scan_contract.py` | P0 |

### AC7.19: GHCR SHA Image Retention (#1277)

> Main and release-branch CI publish backend/frontend `:<sha>` images. The
> scheduled GHCR retention lane must keep these tags bounded without touching
> release tags or the SHA backing a currently live staging/production deploy.
> If live deploy SHA discovery fails, the job fails before deleting package
> versions.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.19.1 | The scheduled GHCR retention workflow prunes only backend/frontend `:<sha>` package versions older than 28 days, never prunes `vX.Y.Z` release tags, preserves live staging/production deploy SHAs resolved from health `git_sha`/`version`, and fails closed when no live SHA exemption is available | `test_AC7_19_1_retention_selects_only_stale_sha_tags`, `test_AC7_19_1_live_sha_exemption_matches_full_and_short_tags`, `test_AC7_19_1_pruner_requires_live_sha_exemptions`, `test_AC7_19_1_pruner_deletes_selected_versions_only`, `test_AC7_19_1_load_versions_accepts_gh_paginated_slurp`, `test_AC7_19_1_workflow_schedules_28_day_sha_retention_with_live_exemption` | `tests/tooling/test_ghcr_sha_retention.py` | P0 |


## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **PostgreSQL healthy** | `invoke finance_report.postgres.status` returns OK | 🔴 Critical |
| **Redis healthy** | `invoke finance_report.redis.status` returns OK | 🔴 Critical |
| **App healthy** | `invoke finance_report.app.status` returns OK | 🔴 Critical |
| **Domain accessible** | `curl https://report.${INTERNAL_DOMAIN}` returns 200 | 🔴 Critical |
| **API functional** | `curl https://report.${INTERNAL_DOMAIN}/api/health` returns OK | 🔴 Critical |
| **Secrets in Vault** | No secrets in Dokploy env vars or disk | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Database backup automation | Scheduled pg_dump | ⏳ |
| Monitoring integration | SigNoz traces | ⏳ |
| Auto-scaling | Resource limits tuning | ⏳ |

### 🚫 Not Acceptable Signals

- Secrets exposed in environment variables
- Database connection failures
- Frontend cannot reach backend API
- SSL certificate errors

---

## 📚 SSOT References

- [Infra2 AGENTS.md](https://github.com/wangzitian0/infra2/blob/main/AGENTS.md) - AI behavior guidelines
- [platform.domain.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/platform.domain.md) - Domain routing rules
- [bootstrap.vars_and_secrets.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/bootstrap.vars_and_secrets.md) - Secrets management
- [db.vault-integration.md](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/db.vault-integration.md) - Vault integration pattern

---

## 🔗 Deliverables

- [x] `repo/finance_report/finance_report/README.md`
- [x] `repo/finance_report/finance_report/01.postgres/` (full deploy structure)
- [x] `repo/finance_report/finance_report/02.redis/` (full deploy structure)
- [x] `repo/finance_report/finance_report/10.app/` (full deploy structure)
- [x] Update `repo/finance_report/README.md` (if exists)
- [x] Link to Infra-009 in infra2 docs

---

## 🔗 Related Projects

- **Infra2 Reference**: [Infra-009.finance_report_deploy.md](https://github.com/wangzitian0/infra2/blob/main/docs/project/Infra-009.finance_report_deploy.md)

---

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/deployment.md](../ssot/deployment.md) — deployment architecture, Vault, staging, and release rationale.
- [../ssot/environments.md](../ssot/environments.md) — six-environment taxonomy and isolation model.

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Phase 1 | Infrastructure setup | 1h |
| Phase 2 | PostgreSQL deployment | 2h |
| Phase 3 | Redis deployment | 1h |
| Phase 4 | App deployment | 3h |
| Phase 5 | Vault secrets | 1h |
| Phase 6 | Verification | 2h |

**Total estimate**: 10 hours (1 week buffer)

---

## 📝 Change Log

| Date | Change |
|------|--------|
| 2026-01-10 | Project created, submodule added |
| 2026-01-27 | All phases completed, production deployment verified |
