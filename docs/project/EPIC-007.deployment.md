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

> (AC7.6.1 removed, duplicate: its test, `test_config_sync_with_env_example`,
> was already fully migrated to
> [`common/runtime/contract.py`](../../common/runtime/contract.py)'s `roadmap`
> as `AC-runtime.18.2` — this row was a stale duplicate.)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC7.6.2 | Required secrets documented | Manual verification | `.env.example` | P0 |

> The config↔manifest env-var guardrail lives in the `runtime` package roadmap
> (`common/runtime/contract.py`) as `AC-runtime.2.1` (#1579): every `config.py`
> env var is either one of a declared dependency's env vars in the
> `DependencyManifest` or a reasoned non-dependency entry — an unclassified new
> env var fails CI, so a new external backend cannot bypass the manifest.
> Its enforcement sibling is `AC-runtime.3.1` (#1577): `boot.validate` FULL
> derives the dependency set from `DEPENDENCY_MANIFEST.required_for(tier)`
> (tier resolved from `ENVIRONMENT` via `resolve_env_tier`, unknown → strictest)
> instead of a hardcoded per-mode list. The remaining enforcement ACs also live
> in the `runtime` roadmap: `AC-runtime.4.1` (#1580 — a probe adapter for every
> declared dependency), `AC-llm.6.2` (#1581 — the LLM cassette substitute is
> input-keyed, runtime invariant 5, owned by the `llm` package), `AC-runtime.6.1` (#1578 — smoke ↔ declaration
> parity via `/health?full=1`, invariant 6); the real-StorageService pipeline
> substitute (invariant 4, #1520) is `AC-runtime.23.1-2` (migration closeout
> continuation, #1663 / #1714).

### AC7.7: Health Checks — migrated to the `runtime` package

> The `/health` dependency-presence ACs (were `AC7.7.*`) moved into the
> `runtime` package roadmap (`common/runtime/contract.py`) as
> `AC-runtime.7.1` · `AC-runtime.7.2` — `/health` returning 200 when all declared
> dependencies are present and 503 when one is absent is `runtime`'s invariant 2.
> (Deployment-topology / manual-status ACs, e.g. `AC7.9.*`, stay in this EPIC —
> that is infra2's domain.)

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

> (AC7.9.7 removed, duplicate: `test_health_when_all_services_healthy` was already migrated to `AC-runtime.7.1`.)
> (AC7.9.8 removed, duplicate: `TestConfigContract` was already migrated to `AC-runtime.18.2`.)
>
> Both live in [`common/runtime/contract.py`](../../common/runtime/contract.py)'s `roadmap`.

### AC7.10: Promote and Release Pipeline Integrity

> (AC7.10.1 / .2 / .3 / .4 / .5 removed, canonical: all five rows are proven by
> one test, `test_AC7_10_production_release_promotes_not_rebuilds`, and
> migrated together into [`common/meta/contract.py`](../../common/meta/contract.py)'s
> `roadmap` as `AC-meta.release-pipeline.1`, migration closeout wave 3,
> #1663.)

### AC7.11: Database Migration Risk Governance

> Migrated to [`common/meta/contract.py`](../../common/meta/contract.py)'s
> `roadmap` (migration closeout wave 3, #1663): `AC-meta.migration-risk.1`
> through `.5`. Migration risk governance is a repo-wide CI/release gate, not
> a specific backend domain's behavior, so it's homed in `meta` alongside the
> other repo-mechanical governance gates (doc-consistency, ssot-governance,
> coverage-tiers).

### AC7.12: Delivery App/Infra-boundary calibration (#876)

> Framework doc-of-record lives in issue #876 (G1–P3).
>
> (AC7.12.3 removed, canonical: migrated to `AC-meta.infra-boundary.1` / `.2`.)
> (AC7.12.4 removed, canonical: migrated to `AC-meta.infra-boundary.3` / `.4` / `.5`.)
> (AC7.12.6 removed, canonical: migrated to `AC-meta.infra-boundary.6` / `.7`.)
> (AC7.12.8 removed, canonical: migrated to `AC-meta.infra-boundary.8`.)
>
> All eight records live in
> [`common/meta/contract.py`](../../common/meta/contract.py)'s `roadmap`
> (migration closeout wave 3, #1663) — one record per underlying test
> function.

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

### AC7.14: Effective Production App Env Verification (#575) — RELOCATED to infra2

> **Relocated out of this app EPIC (#1518 / #1435).** Effective-config verification is infra2
> `deploy_primitive` *behavior*, owned and behaviorally self-tested by infra2
> (`repo/libs/tests/test_deploy_primitive.py`: `test_verify_effective_config_hash_*`,
> `test_wait_for_rollout_*`, `test_preflight_vault_token_*`, `test_deploy_with_wait_snapshots_*`).
> These were app ACs only because app tests mirrored infra2 source to prove them; the boundary
> fix (App emits / Infra consumes) is that infra owns and tests this, app does not. Infra2
> ownership tracked in #1518 — app no longer carries AC7.14.x.

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

> This row removed — migrated to the `runtime` package roadmap as
> `AC-runtime.22.1` (migration closeout continuation, #1663 / #1714).


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
| Monitoring integration | OTLP traces (backend infra2-owned) | ⏳ |
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
