# CI/CD and Test Optimization SSOT — Deploy Half

> **SSOT Key**: `ci-cd` (deploy half)
> **Source of Truth** for post-merge staging/production deploy workflows, smoke
> tests, and deploy E2E gates. Split at #1822 (SSOT dissolution) from the
> pre-split `docs/ssot/ci-cd.md`: the test-pipeline half —
> [common/testing/ci-cd.md](../testing/ci-cd.md) — owns CI job structure, the
> coverage/no-regression gates, and test optimization. Section integrity is
> preserved across the split; no content was dropped.

*Extracted from [development.md](../meta/development.md) — see that file for Moon commands and local setup.*

---

## Deploy Implementation

The following implementation notes were extracted verbatim from the
`## Test Optimization` > `### Implementation` bold-list in the pre-split
`docs/ssot/ci-cd.md` — they describe deploy/release workflow behavior, not
test-pipeline scoping. The test-pipeline half is
[common/testing/ci-cd.md](../testing/ci-cd.md).

**Post-merge staging deploy health gate** (`.github/workflows/deploy.yml`):
- Non-LLM smoke/E2E tests run in parallel with `-n 4`.
- The shared E2E setup action caches `.venv` and Playwright browsers so staging, manual AI/OCR, PR preview, and production smoke runs do not repeatedly download identical E2E dependencies.
- PR CI validates backend and frontend staging image builds without pushing so Dockerfile, context, and build-argument errors are blocked before merge. Main push CI builds and pushes SHA-tagged staging images in parallel with tests when heavy CI is required. These images are immutable commit artifacts and do not move the live `staging` tag.
- Staging deploy is manual (`workflow_dispatch`) only and does not auto-follow main; CI is the development quality gate, not an auto-deploy trigger. The deploy job does not poll or wait for CI. A manual dispatch always performs a real deploy for the chosen release `version_ref`, which must be a `vX.Y.Z` tag with images already published by `deploy.yml`.
- The workflow still emits normalized staging/provider gate outputs for the downstream jobs, but manual dispatch forces staging, provider connectivity, and AI/OCR relevance to `manual-dispatch`. There is no diff-based skip inside the deploy workflow; the diff-based change classifier remains for CI/PR scoping only.
- Staging resolves the dispatched release `version_ref` through `tools/resolve_release_coordinate.py`, checks out that exact tag, and derives the release commit SHA plus pinned infra2 `iac_ref`. The resolver validates the exact `version_ref` string (no whitespace trimming) and fetches only the requested tag without `--force`, so moved release tags or padded inputs fail closed. Staging is a pre-prod canary: approx prod, only slightly ahead.
- The tooling-coverage job installs the same immutable `infra2-sdk v0.3.0` wheel pinned by the backend dev lock so the side-effect-free App-to-Infra request contract is tested in CI without installing or importing infra2 source.
- Staging deploy context artifacts record run metadata, the release `version_ref`, checked-out commit SHA, correlated infra2 receiver run id, image names, pre-deploy staging version, and structured failure domain, failed step, and failure summary. Early failures are split between checkout/release-coordinate resolution, classification normalization, uv/Python/request dependency setup, receiver validation/deploy, public route health, E2E setup, and application smoke/E2E without manually scraping the raw job log first. The classifier fails closed: a failed classification step is never reported as `not-required`, and an unexpected failed step is reported as `unclassified-build-deploy-failure` rather than `none`.
- Main CI builds SHA-tagged images. `deploy.yml` promotes main-CI SHA images to the immutable release tag (`:vX.Y.Z`) with `docker buildx imagetools create --prefer-index=false` and verifies promoted digests; staging deploy consumes the release tag without rebuilding, retagging, or moving a `staging` tag. The commit image tag is exactly the first 7 hex characters of the release commit (`sha7`); deployment workflows must not rely on Git's adaptive `--short` length.
- The report-branch-main preview is the only automatic main-following preview.
  Its app-side sender runs after successful `CI` `workflow_run`, not directly on
  `push`, so backend/frontend SHA images have been published before infra2 is
  notified. The infra2 receiver passes branch-form `main` to `deploy_v2` and
  requires that resolution to match the exact completed CI SHA from the
  `repository_dispatch` payload, preventing newer in-progress main pushes from
  racing GHCR image publication.
- Deploy health covers deploy_v2/Dokploy rollout, effective-config verification, `/api/health`, shell smoke checks, and core non-LLM E2E.
- Runtime incident classification for route, dependency, observability, secrets, stale-version, and flapping failures is owned by [runtime-incident-response.md](./runtime-incident-response.md). This CI/CD SSOT owns where the gates run and what they block, not the shared incident playbooks.
- The fixed staging/prod deploy path uses the infra2 Python Dokploy client. It reports method, endpoint, HTTP status, and reason phrase on API failures, but never raw response bodies, auth headers, or full environment payloads.
- Staging deploy proof is not satisfied by an accepted `repository_dispatch`. `tools/app_deploy_transport.py` watermarks infra2's receiver workflow runs before dispatch, requires exactly one new run, waits for its successful conclusion, and verifies the logs contain the exact request id. The infra2 receiver owns deploy dependency preflight, Dokploy rollout/effective-config verification, and terminal deployment proof. `tools/health_check.sh` remains the App's final target-version proof and must read `/api/health.git_sha` or `/api/health.version` matching the release `version_ref`.
- Provider-backed AI/OCR validation runs as a right-shifted regression record in the same serialized deploy workflow unit when the normalized staging provider gate is required. Staging deploy is manual (`workflow_dispatch`) only: workflow-level singleton concurrency (`group: staging-deploy`, `cancel-in-progress: false`) admits one active staging train unit at a time, so only one `Deploy Staging` run mutates staging at a time. The concurrency group is the sole serialization mechanism, so no in-job train wait is needed.
- The lightweight AI provider connectivity smoke lives in the dedicated `Staging Provider Gate` job and runs only when `provider_gate_required.staging` is true. This single real chat round trip proves staging Vault/provider credentials, base URL, and primary model routing before the full PDF OCR replay spends provider quota. The full OCR/LLM replay remains gated to provider, extraction, statement parsing, PDF fixture, AI/OCR workflow, or critical LLM proof path changes and starts only after the provider connectivity smoke passes.
- The provider connectivity smoke is resilient to transient provider unavailability so a flaky upstream cannot red `main`. It retries the round trip with exponential backoff, then classifies the last observed outcome: a client/config `4xx` is a hard delivery gate (`config-failure`), while a `5xx`, timeout, or empty response is treated as transient and reported as a non-blocking `degraded` status. A degraded smoke still surfaces in the step summary, provider-gate artifact, and `Post-merge Delivery` as `degraded-provider`, but it does not fail post-merge delivery. Provider configuration regressions therefore still block, transient provider blips do not.
- Transient toolchain-download retry: the staging deploy path runs shell steps that download tools over the network — the shared `setup-e2e-tests` composite and the exact infra2 SDK plus `httpx` request dependencies. These are bounded-retry wrapped with exponential backoff; on exhaustion the original external error is printed before the step exits non-zero. Application/test execution steps stay fail-fast so deploy or test failures are never masked by retries.
- Concurrent manual staging dispatches are serialized solely by the workflow-level singleton concurrency group (`group: staging-deploy`, `cancel-in-progress: false`); only one `Deploy Staging` run mutates staging at a time. This keeps deploy, smoke, E2E, provider connectivity, and required AI/OCR proof as one ordered train unit for the workflow that owns the staging slot.
- Staging serial queueing bottleneck can be bypassed via parallel staging. The proposed path to parallel staging is to introduce multiple staging slots (e.g., `staging-1`, `staging-2`) or dynamic ephemeral staging environments using Docker Compose on the VPS, where each train unit or PR has its own ephemeral staging stack. This would allow multiple staging runs to execute in parallel, using a pool of database/MinIO instances, and dynamically routing to them via Traefik. This would bypass the serial bottleneck.
- The staging deploy-health job has a 75-minute deploy-health job timeout, and the E2E step has a 22-minute E2E step timeout. The deploy health probe waits up to 600 seconds for `/api/health` to report the target release `version_ref` so normal Dokploy/Traefik rollout lag does not fail before the deployed tag becomes visible. If `/api/health` is reachable but repeatedly reports the same stale version, `tools/health_check.sh` fails earlier with a Dokploy/image-pull/Traefik stale-route diagnosis instead of spending the full health window on a stable old deployment. The E2E command logs `[phase:start]` and `[phase:end]` records for smoke and core non-LLM E2E so timeout and latency failures identify the active phase.
- The reusable `staging-ai-ocr-gate.yml`'s job/step `timeout-minutes` (#1767, AC8.13.167) is sized per `corpus` input off the corpus's total sequential parse-wait count (`tools/staging_ai_ocr_gate_contract.py` `totals()['uploads']`: canary=2, audit_replay=11, all=13 — pytest runs single-worker, so every wait is serial) times the 8-minute `PARSING_TIMEOUT_MS` ceiling plus overhead, not one fixed value: the corpus pytest step gets 25/100/115 minutes (canary/audit_replay/all) and the job gets 125 minutes, so a full-outage night can still finish the whole corpus and produce JUnit evidence. A `gate_timeout_fallback` job step (AC8.13.166) runs `if: always()` and fires the same GitHub-issue fallback alert whenever the corpus step's outcome is not `success` and it produced no `ai_ocr_status` output — i.e. it died before its own `record_and_finish` — using a distinct `gate-timeout` status so a diagnostics-blind failure (the corpus step killed by its own budget before alerting) can never go unreported, independent of whether the budget above was sized correctly.
- The staging AI/OCR gate machine-attributes every red before alerting (#1806, AC-testing.deploy-gates.37–40). After the version check and before the corpus spend, a preflight reads the deployed `/api/health` surface (manifest-required dependency checks only — the gate recomputes no parallel environment state); a miss records the distinct `precondition-failed` status. On a red corpus run, `tools/staging_ai_ocr_gate_contract.py --classify-junit` attributes each failed case to `regression | precondition | transient` (regression-first precedence): environment-data gaps (e.g. missing FX rates) record `precondition-failed`, transient-only reds (provider timeout / 5xx) earn exactly one bounded retry of the affected files and otherwise record `provider-transient` — escalating to `regression-failed` when a transient alert is already standing from a prior run, so transience cannot mask a standing regression. The alert-issue body is generated from that attribution (never a hardcoded parse-quality claim), and a green run auto-closes every standing gate alert class with the run as evidence, so an open alert cannot keep asserting a state the gate no longer observes.
- Staging deploys may set `DEPLOY_PRIMARY_MODEL_OVERRIDE`, `DEPLOY_OCR_MODEL_OVERRIDE`, and `DEPLOY_VISION_MODEL_OVERRIDE`; the current post-merge gate pins `PRIMARY_MODEL=glm-5.1`, `OCR_MODEL=glm-4.6v`, and `VISION_MODEL=glm-4.6v`.
- Repeated `/api/health` 404 responses are treated as route failures, not generic backend failures: the health script emits structured `route_probe` lines and probes `/api/ping` and `/` so logs distinguish a missing or shadowed Traefik API route from an unhealthy backend container.
- The infra2 receiver owns deploy dependency preflight: Vault/AppRole token checks and post-deploy effective `IAC_CONFIG_HASH` verification are default-on for fixed staging/prod deploys. Finance Report owns immutable image/evidence selection, canonical request rendering, receiver-run correlation, health, smoke, non-LLM E2E, and provider 4xx/config gates.
- Dokploy API failures must not print raw response bodies. Shared shell helpers still report only endpoint, HTTP status, safe message fields, and `raw_body_printed=false` for preview/cleanup paths; the fixed deploy_v2 path raises sanitized Python client errors. Compose responses can include environment data and refresh tokens, so raw compose/deployment/env payloads stay out of GitHub Actions logs.
- Staging and production deploys write only the allowlisted fixed-env keys required for runtime identity, routing, telemetry, and model overrides. The effective-config verification reads back `IAC_CONFIG_HASH`; full environment strings and secret-like keys must not be logged. Stale effective config is fail-closed: correct the Dokploy/env issue and perform a manual rerun of the same deploy_v2 workflow.
- The post-merge workflow appends a GitHub Step Summary after deploy health and AI/OCR finish, making queue time, serial execution time, and slow jobs visible without manually scraping logs.
- The deploy workflow also emits a dedicated `Post-merge Delivery` check. This aggregate check fails when build/deploy, provider `4xx`/unknown hard failure, or the exact-SHA AI/OCR statement canary fails, and passes when the release-critical deploy validation unit is complete or when classification proves staging is not required. A green `CI` workflow alone is not sufficient evidence that post-merge delivery passed.

**Release gate reclassification**
- Left-shifted: deterministic AI/OCR gate risks that do not require a live provider are checked before merge by tooling contracts for isolated users, browser-cookie API calls, deterministic waits, and the staged corpus manifest. Production release also checks the exact `Deploy Staging <version_ref>` run name before mutation so loose tag substring matches cannot select the wrong staging evidence.
- Strengthened: release-critical gates remain hard blockers for immutable release images, deploy_v2 rollout records, effective-config verification, route health, shell smoke, core non-LLM E2E, and provider connectivity `4xx`/config failures. Production eligibility now inspects the selected staging run's required jobs (`Deploy Staging` and `Staging Provider Gate`) instead of trusting only a run-level conclusion.
- Removed: the comprehensive staging AI/OCR audit replay is not a hard `Post-merge Delivery` failure and does not block production solely through the staging workflow's aggregate conclusion. A full-provider business regression outside the minimal canary remains diagnostic evidence.
- Right-shifted: the comprehensive staging AI/OCR report-package replay runs after deploy health and provider smoke, but failures are recorded in step summaries and artifacts for issue triage. The manual `deploy.yml` workflow remains a blocking on-demand diagnostic gate for teams that explicitly choose to rerun that provider-backed corpus.

**AI/OCR Canary vs Audit Replay** (issue #1232):
The provider-backed AI/OCR corpus is split into two distinct gates that share one reusable gate body (`staging-ai-ocr-gate.yml`, selected by its `corpus` input) so they cannot drift:

- **`AI/OCR Canary`** (blocking-path, minimal): the production-promotion path runs only the smallest corpus that answers one question — *can the exact deployed staging release perform the real-provider upload → parse → import → value path users need in production?* It is `corpus: canary` = `tests/e2e/test_brokerage_upload_to_portfolio_value.py` (one representative brokerage upload, parse, position import, and non-zero portfolio/report value) and makes **no** broad audit assertions (`report_verifications == 0`). The canary's provider transient classification is owned by the `Staging Provider Gate`: the canary runs only after that gate passes, where a `4xx`/config error blocks delivery and a `5xx`/timeout is a non-blocking `degraded` status. The inline `deploy.yml#ai-ocr-gate` pins both checkout and version assertion to `commit_full_sha` and runs it fail-fast (`blocking: true`).
- **`Audit Replay`** (nightly/manual, comprehensive): the heavy LLM journeys — full statement journey, four-asset net-worth golden path, personal financial report package, and CSV/traceability assertions — run in `.github/workflows/audit-replay.yml` on a nightly `schedule:` plus `workflow_dispatch:`, calling the same reusable gate with `corpus: audit_replay` and `blocking: false`. Audit Replay is recorded evidence for triage; it does **not** block production promotion by default. The canary corpus (`canary_files()`) and audit corpus (`audit_replay_files()`) are disjoint and partition the full derived `llm` post-merge corpus, and a newly-added heavy `@ac_proof` journey defaults to audit-replay (by subtraction) so it can never silently creep into the blocking canary. The `deploy.yml#manual-ai-ocr-gate` recovery diagnostic runs the full corpus (`corpus: all`) fail-fast for explicit human reproduction. This canary-vs-audit split is a recorded `keep_separate` decision in `common/meta/data/ci-gate-inventory.yaml`.

**Post-merge staging AI/OCR gate** (`.github/workflows/deploy.yml`):
- Automatic `Staging AI/OCR Gate` execution lives in `.github/workflows/deploy.yml` and starts only after deploy health succeeds in the same serialized post-merge workflow unit. Its minimal canary is a release-critical blocker for that exact deployed commit; the comprehensive audit replay remains recorded diagnostic evidence.
- `.github/workflows/deploy.yml` remains as a manual recovery entry point via `workflow_dispatch` for rerunning provider-backed validation against the currently selected ref.
- The AI/OCR regression runs as part of a manual staging dispatch (it inherits the deploy workflow's `workflow_dispatch` trigger) before spending provider quota, and can also be invoked on demand via `deploy.yml`. The on-demand workflow blocks its own run because it exists for explicit provider-backed diagnosis.
- Tests marked `llm` are the only tests allowed to call the configured AI/OCR provider and run once, serially, in this provider-backed gate.
- PR CI does not spend real OCR/LLM quota, but tooling tests must still left-shift deterministic gate risks: every staging AI/OCR gate test must use isolated user fixtures, browser-cookie auth for in-browser API calls, and deterministic UI or route waits; contract tests reject shared mutable users, localStorage bearer tokens, and generic deployed-environment idle waits before merge.
- The automatic canary passes the emitted full commit SHA as both `commit_ref` and `EXPECTED_SHA`; the reusable gate normalizes that SHA to the published short image tag before checking the deployed health surface. Frontend readiness separately checks the baked short SHA from the release commit before browser E2E starts.
- The automatic gate checks out the full SHA emitted by `build-and-deploy` before setting up E2E tests. This keeps the test code, audit context, and deployed image under validation aligned to the same commit instead of the newest `main` ref.
- The GLM-backed PDF gate allows a longer parsing window than normal UI tests: JSON extraction requests use `AI_JSON_TIMEOUT_SECONDS=360`, and the browser gate waits up to `PARSING_TIMEOUT_MS=480000` so slow but successful `glm-4.6v` PDF parsing is not misclassified as a failed provider gate.
- The full GLM corpus (`corpus: all`) includes `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_statement_upload_e2e.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, and `tests/e2e/test_personal_financial_report_package.py`. The blocking deploy path runs only the `canary` subset of these (`test_brokerage_upload_to_portfolio_value.py`); the remaining heavy journeys run as the `audit_replay` corpus in `audit-replay.yml` (nightly + manual). The brokerage canary test uploads Moomoo and Futu PDF fixtures through `/api/statements/upload`, waits for parsed statements, imports positions through `/api/statements/{id}/brokerage/import`, and verifies `/api/portfolio/holdings` plus `/api/reports/balance-sheet`. The four-asset gate (audit-replay corpus) uses an isolated user to combine deterministic bank statement posting, brokerage PDF import, property/mortgage/ESOP manual valuation snapshots, exact as-of net worth, and dashboard/report totals. The personal financial report package gate (audit-replay corpus) verifies statements, schedules, notes, restricted-asset treatment, report exports, and source traceability from one fresh user. Failures identify whether OCR parsing, parsed-data state transition, brokerage import, manual valuation, reporting, report packaging, or dashboard aggregation failed. The path-level proof matrix is maintained in [EPIC-017](../../docs/project/EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix) with the compact entry-point version in the README; critical product proof anchors are a derived view of the AC graph, validated by the `check_critical_proof_matrix` contract folded into the single `tools/check_ac_index.py` gate (macro outcome source: `common/testing/data/critical-proof-outcomes.yaml`). Every `post_merge_environment` proof in that matrix that carries the `llm` marker appears in exactly one of the two corpora — the minimal `canary` (deploy blocking path) or the comprehensive `audit_replay` (`audit-replay.yml`) — and the on-demand `manual-ai-ocr-gate` recovery diagnostic in `.github/workflows/deploy.yml` runs the full corpus.

**PR preview E2E** (`.github/workflows/preview.yml`):

> The trigger/blocking contract for every delivery gate is the SSOT
> [`delivery-gates.yaml`](../meta/data/delivery-gates.yaml) (verified by
> `tests/tooling/test_delivery_gates_contract.py`). This section describes the
> *behavior*; it does not own the trigger *mechanism* — change a trigger there.

- The in-runner E2E gate runs **synchronously on `pull_request`**
  (opened/synchronize/reopened), so it is a real required check a fast or auto
  merge cannot bypass. It no longer follows CI asynchronously via `workflow_run`:
  that fired only after CI and a quick merge could land before it ran as a gate
  (GitHub counts a skipped required check as passed). It is image-free, so it needs
  no CI artifact and runs independently of CI. PR close triggers cleanup, not a gate.
- PR preview injects no REAL provider key: the in-runner stack wires a
  placeholder `ZAI_API_KEY` with an unroutable `AI_BASE_URL` (so the app
  reports LLM wiring configured and the first-run provider modal stays out of
  browser E2E, #1589) while an accidental provider call fails instantly —
  app wiring is validated without real GLM/OCR provider calls.
- PR preview does not push, preflight, pull, or delete PR preview images, and it
  does not build images in CI. The `build-preview-backend-image`,
  `build-preview-frontend-image`, `gate-cheap-ci`, and GHCR preflight/delete
  jobs are removed. The post-merge staging ladder remains the first place
  registry images are born, pushed, and validated.
- The runner stack uses `docker-compose.yml:docker-compose.ci-e2e.yml`,
  `COMPOSE_PROFILES=infra,app`, `APP_URL=http://localhost:8080`, and
  `GIT_COMMIT_SHA=<PR head SHA>`. The runner stack waits for `/api/health` before smoke/E2E, caps readiness at 300 seconds, emits compose logs on
  failure, and then always runs `docker compose down --volumes
  --remove-orphans`.
- A persistent Dokploy preview is **on-demand only** (P1a-2, #879): the
  `deploy-preview` job runs solely via manual `workflow_dispatch` (Run workflow →
  PR number), never automatically per PR. When triggered, after the in-runner E2E
  gate passes it is GitHub-source: Dokploy clones the PR branch and runs
  `docker compose ... up -d --build` so the backend/frontend are
  **built from the PR source on the Dokploy host** — no GHCR image is pulled or
  pushed. This app-side persistent PR preview path is not the infra2 `deploy_v2 preview/*` front door;
  `deploy_v2 preview/branch` currently owns the
  `report-branch-main`/canary style preview slots. The job is `continue-on-error`
  and is not a required check, so a preview failure never blocks the PR; the
  in-runner E2E is the merge authority. The persistent URL is
  `https://report-pr-<N>.<domain>`.
- `tools/pr_preview_lifecycle.py` is the single owner for preview **deploy**
  (standing previews up). The workflow does not hand-roll separate Dokploy shell
  blocks, so the deploy keeps one naming, metadata, logging, and redaction
  contract. Reclaim (teardown/reconcile) is not app-owned — it is dispatched to
  infra2 on PR close (see the reclaim bullets above).
- PR preview Dokploy API responses are parsed for required fields only.
  Workflows must not print raw Dokploy response JSON because compose responses
  can include environment data and refresh tokens.
- The in-runner E2E result comment and context artifact record
  `preview_runtime=github-runner-compose`,
  `persistent_preview_url=https://report-pr-<N>.<domain>`,
  `registry_image_push=false`, and
  `dokploy_deploy=after-e2e-non-blocking-build-from-source`. The persistent
  preview URL is posted as a separate non-blocking comment.
- Persistent preview reclaim is infra2-owned: on PR close `preview.yml#cleanup`
  dispatches a vendor-neutral `preview-teardown` signal (`repository_dispatch`,
  `INFRA2_PAT`) to infra2, which performs the authoritative idempotent 1:1
  teardown by PR number — the app never calls the Dokploy API *for reclaim*. The
  deploy path is still app-side (get-or-create + redeploy), so it updates the
  preview in place across commits without a pre-deploy delete.
- PR preview rollout proof fails fast on a missing deployment record. When
  Dokploy reports `composeStatus=done` but never exposes a **new** deployment
  record for the requested SHA within the new-record window,
  `wait_for_dokploy_deployment_rollout` raises the classified
  `DokployNoNewDeploymentRecord` error
  (`platform_failure_domain=dokploy-worker-or-deployment-record`) instead of
  proceeding to commit-scoped readiness. This stops the lifecycle from
  false-greening against stale records and then wasting the full readiness
  window probing a route for a SHA that never rolled out. The diagnostics
  distinguish "no new deployment created" (control-plane / worker failure) from
  "new deployment created but route not ready" (a readiness/Traefik 404 window),
  so a 404 is no longer the only signal. The retry ladder still recovers via
  `compose.redeploy` and compose recreation because the classified error
  subclasses `DokployDeploymentDidNotStart`.
- PR preview deploy never leaves a silent half-update. The deploy mutates the
  Dokploy compose (source then env) before triggering the rollout, so the
  failure path captures the last-known-good source/env of an existing compose
  before mutating. On a deploy/rollout failure it either rolls the compose back
  to that last-known-good state (`recovery_state=rolled-back`) or, when no good
  snapshot exists (a freshly created or recreated compose), explicitly marks the
  record safe-to-reconcile (`recovery_state=marked-safe-to-reconcile`). The
  failure context records which mutation step (`source`, `env`, `deploy`, or
  `rollout`) the compose was left at. `update_compose_env` additionally
  reconciles the **whole** requested env against the effective remote env so a
  stale non-allowlisted key from a prior deploy cannot diverge unnoticed;
  divergence fails fast with key-name-only diagnostics that never print env
  values.
- PR preview E2E explicitly excludes tests marked `llm`. The post-merge `Staging AI/OCR Gate` workflow is the single automated CI entry point that may spend provider quota.
- PR preview non-LLM E2E is a strict preview-relevant subset **derived from the execution matrix** (`common/testing/matrix.py`, issue #1547): the workflow evals `python tools/test_selection.py --stage pr_preview_e2e --shell` at runtime instead of hardcoding a whitelist. A root E2E spec enters the pre-merge set only when its matrix row is audited AND declares no external needs (provider quota, market data, deployed-env probing, state-sensitivity); everything else remains a staging/post-merge responsibility, and an unaudited spec can never silently creep into the merge-blocking path.
- The shared `.github/actions/setup-e2e-tests` action owns E2E Python import setup. It must export the repository root through `PYTHONPATH` via `$GITHUB_ENV` before preview, staging, AI/OCR, or production E2E pytest commands run, because `tests/e2e/conftest.py` imports shared helpers through the `tests.e2e.*` package path while pytest may choose `tests/e2e` as its root directory.
- PR-preview reclaim is infra2-owned and event-driven: on PR close the app
  dispatches a `preview-teardown` signal and infra2 performs the idempotent 1:1
  Dokploy teardown; infra2's hourly `preview-leak-check` detects + alerts on
  anything a close event missed. The app's scheduled `PR Preview Cleanup` job only
  prunes legacy closed-PR backend/frontend GHCR tags matching `pr-<number>-<sha>`
  after the 14-day retention window while preserving tags for open PRs. GitHub
  workflows must not SSH to the VPS or call the Dokploy API for PR reclaim.
- The scheduled `GHCR SHA Retention` workflow owns post-merge backend/frontend
  `:<sha>` package retention only. It collects live staging and production
  health refs, resolves release tags back to commit SHAs when needed, and uses
  `tools/ghcr_retention.py` to delete stale SHA package versions older than 28
  days. It never owns PR preview `pr-<number>-<sha>` cleanup and never deletes a
  package version carrying a `vX.Y.Z` release tag.
- The retired `tools/cleanup_pr_preview_resources.py` compatibility entry point is removed. Closed-PR Dokploy reclaim is infra2-owned (event-driven `preview-teardown` + the hourly `preview-leak-check`); generic VPS host hygiene is also infra2-owned (infra2's `tools/host_hygiene_schedule.py` + the ops-checks re-ensure job).
- PR preview containers created from `docker-compose.yml` use the `json-file` logging driver with bounded `max-size` and `max-file` options so Docker container logs cannot grow without limit.
- Generic VPS host hygiene is **infra2-owned** (deployment-environment GC belongs to infra2; see infra2 `docs/ssot/ops.pipeline.md §11`). It runs as a Dokploy `dokploy-server` Schedule Job — provisioned by infra2's `tools/host_hygiene_schedule.py` and kept ensured by infra2's `ops-checks` host-hygiene job — pruning old stopped non-preview containers, build cache, unused images, all unused Docker networks, oversized Docker json logs, and the systemd journal. The app no longer ships a host-hygiene tool or provisions the schedule. PR preview environments are reaped by infra2's preview teardown/leak-check, never by host hygiene; the `PR_PREVIEW_CONTAINER_PATTERN` (now in infra2) only *excludes* preview containers from generic pruning.
- GLM/OCR CI traffic uses `AI_BASE_URL=https://api.z.ai/api/coding/paas/v4`; the URL remains an env override so the base provider can be replaced without code changes.

**Production release dry-run** (`.github/workflows/deploy.yml`):
- Manual `workflow_dispatch` with `dry_run=true` sets up the configured `PYTHON_VERSION`, resolves the target release `version_ref`, uses `tools/verify_release_evidence.py` to verify the tag commit has successful `main` CI, `deploy.yml` published release images, and the exact `Deploy Staging <version_ref>` run has successful release-critical jobs, then runs release lint, checks migration risk, and uses `tools/verify_release_images.py` to fetch release image digests without mutating production. The production deploy job uses the same pinned-Python release tools before mutation so dry-run and deploy cannot drift.
- The dry-run reports the validated `version_ref`, release commit, main CI run, `deploy.yml` release-image promotion run, staging run, target image digests, and states that production mutation was skipped. No rebuild occurs.
- Tag pushes promote versioned release images only through `.github/workflows/deploy.yml`. Manual dispatch with `dry_run=false` remains the production deploy path for an existing required `version_ref`.
- Production backend release images are addressed by the release version tag, and deploy_v2 injects the release version tag as runtime `IMAGE_TAG` / `GIT_COMMIT_SHA` so `/api/health` can prove the deployed version even after a same-tag redeploy.
- Production deploys run `tools/production_infra_smoke.py` after health check. That gate verifies the deployed version, `/api/health` dependency checks for database and S3, read-only `/api/ping`, and frontend reachability before production smoke and read-only E2E run. (Proving the observability backend actually ingests the deployed version is infra2's job, not the app deploy gate.)
- Production release rollback uses the infra2 receiver: when a correlated receiver run mutates production successfully but route health, infrastructure smoke, application smoke, or read-only E2E fails, the workflow renders a second canonical Production request for the recorded `production_before_rollback_ref`, verifies its release/staging/review evidence, and confirms `/api/health` reports that release tag. If pre-deploy health exposes only a SHA or another non-release value, the workflow warns and leaves the original post-deploy failure as authoritative.
- Production deploy context records the pre-deploy health status, `production_before_version`, `production_before_health_version`, `production_before_git_sha`, `production_before_rollback_ref`, image verification outcome, deploy-health outcome, infrastructure smoke outcome, application smoke outcome, read-only E2E outcome, rollback outcome, rollback-unavailable outcome, and a small failure-domain classification. Production still proves release integrity and health only; first-time business correctness remains owned by PR and staging gates.


---

## Current Performance Metrics (Deploy)

**Post-merge staging (2026-05-20 observed baseline):**
- Build and deploy job execution: **~5m 19s**.
- Automatic AI/OCR gate execution: **~4m 38s**.
- AI/OCR `Setup E2E Tests`: **~2m 54s** before E2E virtualenv and Playwright browser caching.

**Release image promotion (2026-05-21 target, updated to tag-based staging):**
- Main push CI owns SHA-tagged image creation for heavy runtime changes.
- `deploy.yml` promotes existing SHA images to the immutable `vX.Y.Z` release tag on tag push, avoiding redundant Docker builds when the `:<sha>` image already exists from CI.
- Staging and production consume the release `version_ref` through deploy_v2; missing release images fail closed before any Dokploy mutation.


> **Test-pipeline performance metrics** (CI job timing) live in the
> test-pipeline half: [common/testing/ci-cd.md](../testing/ci-cd.md#current-performance-metrics).

---

## Smoke Tests (`tools/smoke_test.sh`)

```bash
# Local (after starting servers)
bash tools/smoke_test.sh

# Against staging/prod
BASE_URL=https://report.zitian.party bash tools/smoke_test.sh
```

| Endpoint | Check |
|----------|-------|
| `/` | Home / dashboard page loads (there is no separate `/dashboard` route) |
| `/accounts` | Accounts page loads |
| `/journal` | Journal page loads |
| `/statements/upload` | Statement upload page loads (there is no bare `/statements` page) |
| `/reports` | Reports page loads |
| `/reconciliation` | Workbench loads |
| `/login` | Login page loads |
| `/api/health` | Returns "healthy" |
| `/api/docs` | Swagger UI loads |
| `/api/ping` | Ping API responds |

> Smoke route integrity (AC7.17.1, #411): every page path the shell smoke gate
> asserts must map to a real public Next.js route under `apps/frontend/src/app`.
> `tests/tooling/test_smoke_routes_contract.py` fails if the script asserts a
> path with no `page.tsx` (e.g. the removed `/dashboard` / bare `/statements`).

## Deploy E2E Gates

Staging and production deploy workflows separate basic availability smoke from
deploy-blocking usability gates:

| Environment | Gate | Command | Skip Policy |
|-------------|------|---------|-------------|
| Staging | Shell smoke | `bash tools/smoke_test.sh "$APP_URL" staging` | No skips; any failed check fails deploy |
| Staging | Non-LLM E2E | `STRICT_E2E_GATES=true pytest tests/e2e -v -m "(smoke or e2e) and not llm" -n 4` | Tests marked `critical` must fail instead of skip |
| Staging | AI/OCR Canary (blocking path) | `STRICT_E2E_GATES=true pytest tests/e2e/test_brokerage_upload_to_portfolio_value.py -v -m "llm"` | Minimal upload→parse→import→value liveness; exact-SHA and fail-fast on the deploy path, transient classification owned by the provider gate (issue #1232) |
| Staging | AI/OCR Audit Replay (nightly/manual) | `STRICT_E2E_GATES=true pytest tests/e2e/test_statement_full_journey.py tests/e2e/test_four_asset_net_worth_golden_path.py tests/e2e/test_personal_financial_report_package.py tests/e2e/test_statement_upload_e2e.py -v -m "llm"` | Comprehensive heavy journeys via `audit-replay.yml`; record-only, never blocks production promotion. The full corpus (canary + audit) runs fail-fast only in the on-demand `manual-ai-ocr-gate` recovery diagnostic |
| Production | Shell smoke | `bash tools/smoke_test.sh https://report.zitian.party production` | Read-only checks only |
| Production | Prod-safe E2E | `pytest tests/e2e/test_production_readonly_smoke.py -v -m "prod_safe"` | Authenticated dashboard check may skip only when read-only smoke credentials are absent |

Critical staging non-LLM E2E tests are the proof that a deployment is usable,
not just reachable. `tests/e2e/test_statement_full_journey.py::test_dbs_statement_full_journey`
remains the canonical AI/OCR corpus proof: DBS PDF upload must reach `parsed`,
show transactions, approve, and load the balance sheet. A `rejected` parsing
status is recorded as a full-provider regression in automatic staging because it
can indicate provider, OCR, secret, model config, fixture, or external-state
breakage. Rejection failures include the selected model and statement validation
context (`validation_error`, `confidence_score`, and `balance_validated`) so the
right-shifted evidence is actionable from the CI log.

`tests/e2e/test_vision_upload_to_dashboard_hard_gate.py::test_statement_upload_to_dashboard_vision_hard_gate`
is the deterministic upload-to-dashboard vision hard gate. It runs in the
staging non-LLM deploy gate with a fresh isolated user, uploads a deterministic
CSV fixture, verifies Stage 1 auto-posted journal entries, reruns
reconciliation to a cleared Stage 2 state, asserts Processing visibility, and
checks exact dashboard, balance-sheet, income-statement, and cash-flow totals.

`tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value`
is the upload-to-report portfolio hard gate for Issue #404. It proves that at
least two brokerage PDFs can be parsed by the real configured OCR path, imported
as portfolio positions, and reflected in the latest balance-sheet market
valuation adjustment lines. The gate intentionally does not compare imported
holdings to whole `total_assets`: unrelated staging ledger lines, including
negative cash or bank balances from other E2E journeys, can lower total assets
without invalidating portfolio valuation coverage. Failure output includes the
holdings total market value, valuation adjustment total, non-portfolio asset
total, total assets, net worth adjustment, and relevant asset lines.

`tests/e2e/test_four_asset_net_worth_golden_path.py::test_four_asset_as_of_net_worth_golden_path`
is the north-star net-worth hard gate for Issue #444. It uses an isolated user
to upload bank statement data, explicitly post and reconcile the statement,
import a brokerage PDF, create property, mortgage, and ESOP valuation snapshots,
then prove exact as-of assets, liabilities, net worth, and dashboard/report
totals.

PR preview E2E intentionally runs a strict runtime/API/UI subset derived from
the execution matrix (`common/testing/matrix.py` — audited rows with no
external needs; see the generated selection via
`python tools/test_selection.py --stage pr_preview_e2e`), excludes the `llm`
marker, and does not inject the provider API key. This keeps provider spend and broad
business-regression concurrency concentrated in the post-merge staging job,
where `STRICT_E2E_GATES=true` makes provider/config failures block deploy. PR
preview remains useful for app wiring and non-provider route proof without
turning provider instability or state-sensitive staging regressions into PR
preview noise.


---

## Related

- [deployment.md](./deployment.md) — Dual-repo model, Vault secret injection, staging/production flow
- [environments.md](./environments.md) — Six environment overview
- [runtime-incident-response.md](./runtime-incident-response.md) — Runtime incident triage
- [common/testing/ci-cd.md](../testing/ci-cd.md) — the test-pipeline half (CI job structure, coverage gates, test optimization)
