# Delivery Engine Recommendations

> Owner: EPIC-008 testing strategy
> See: docs/ssot/ci-cd.md

This note captures CI and post-merge optimization items that should stay
separate from routine SSOT edits because they change workflow topology or
branch-protection behavior.

## Current baseline

Observed on June 21, 2026 after the #1252 ROI sequence landed through PR
#1288 at merge commit `ab2630e1`:

| Lane | Recent duration | Main contributor |
|---|---:|---|
| Main CI heavy path | 4m 46s | Seeded 5-way backend shard tail plus unified coverage / AC ratchet fan-in |
| Slowest backend shard | 3m 50s | Backend shard 3/5 in run `27896401849` |
| Frontend browser proof | 2m 45s | Split `frontend-playwright`; frontend is no longer the critical path |
| Unified coverage job | 27s | Artifact fan-in + local unified coverage + main-only Coveralls reporting |

Backend shards in run `27896401849` completed in
3m31s / 3m43s / 3m49s / 3m50s / 3m41s.

#1252 closure readout: the highest-ROI left shifts and convergence work are now
done for this phase. The old single frontend critical path was split, duplicate
frontend production audit was removed, backend sharding was corrected to a
seeded 5-way least-duration split, and production/staging release parameters
were aligned around `version_ref`. The measured bottleneck is now the backend
shard tail, not frontend or fan-in. Do not add more shards until new timing
evidence shows backend tail regression; the next ROI work should be targeted
debt items such as GitHub action runtime governance (#817) and GHCR retention
(#1277), not another topology split.

Observed on May 27, 2026:

| Lane | Recent duration | Main contributor |
|---|---:|---|
| Main CI heavy path | 8m 56s | Backend shard wall time plus unified coverage |
| Unified coverage job | 1m 40s | Local coverage gates plus main-only Coveralls reporting |
| Staging post-merge lane | 18m 04s | Same-SHA CI wait, then deploy and E2E |
| Staging AI/OCR gate | 3m 53s | Provider-backed E2E execution |

## Recommended follow-ups

### Structured matrix consumer migration

The current sparse Env x Stage model is documented in
`docs/ssot/ci-cd.md#env-x-stage-contract` and implemented in
`common/ci/change_classifier.py` through structured outputs:
`env_stage_required`, `env_stage_reasons`, `env_stage_stages`,
`env_stage_files`, and provider-gate JSON outputs. GitHub Actions jobs now
normalize their gates from that structured matrix:

- PR CI reads `env_stage_required.pr` instead of the legacy `heavy_required`
  output.
- PR Preview reads `env_stage_required["pr-preview"]` instead of the legacy
  `pr_preview_required` output.
- Staging reads `env_stage_required.staging` and
  `provider_gate_required.staging` instead of the legacy `staging_required` and
  `staging_ai_ocr_required` outputs.

The legacy scalar outputs remain only as external compatibility shims while
downstream ad hoc consumers migrate.

Latest evidence review on June 9, 2026 sampled the three newest successful and
three newest failed logs for the active CI lanes: `CI`,
`PR Test Environment`, `Deploy Staging`, `Staging AI/OCR Gate`, and
`Production Release`. The pattern supports the current balance:

- PR CI is the deterministic merge authority; recent failures were unified
  coverage regressions, which are cheap to diagnose before deploy.
- PR Preview used to be the noisiest deployed lane; failures concentrated in
  the former Dokploy deploy lifecycle before browser E2E. The current preview
  follows successful PR CI, runs in the GitHub runner, and keeps historical
  Dokploy resources cleanup-only.
- Staging is correctly acting as the post-merge environment gate; recent
  failures were split between Dokploy deploy health and application E2E, then
  surfaced through `Post-merge Delivery`.
- Provider-backed AI/OCR and production release checks are appropriately
  narrow. They prove provider or release integrity only after deterministic PR
  and staging proof exists.

The next code simplification should remove the scalar compatibility shims after
branch protection, required-check behavior, and any external ad hoc consumers
are confirmed to rely only on the structured consumers.

### Sparse matrix evidence audit

June 9, 2026 evidence sample: the review checked the three newest successful
and three newest failed available logs for each active delivery lane. Cancelled
runs were ignored because they prove supersession behavior, not a gate result.
Runtime incident categories such as stale-version, route, dependency,
observability, secrets, and flapping are owned by
[runtime-incident-response.md](../ssot/runtime-incident-response.md). This note
records delivery-engine evidence and recommendations only.

| Lane | Three newest successful samples | Three newest failed samples | Observed signal |
|---|---|---|---|
| `CI` | `27186502313`, `27183789200`, `27183466331` | `27184608585`, `27183552389`, `27183418593` | Failures concentrated in deterministic pre-deploy gates, especially unified coverage, while successful runs kept lint, AC traceability, backend shards, integration, Tier-1 E2E, frontend, image dry-run, tooling coverage, unified coverage, and `finish` aligned. |
| `PR Test Environment` | `27186502312`, `27183466349`, `27183418552` | `27184608593`, `27183789205`, `27183223104` | Failures concentrated in deploy/readiness before browser E2E. This supports keeping preview scoped to image, route, health/version, and provider-free UI/API subset proof. |
| `Deploy Staging` | `27182443187`, `27150045338`, `27135967250` | `27136569205`, `27133497263`, `27115009456` | Failures were environment/deploy-health/E2E class failures, not first-time deterministic business-proof failures. Staging remains the right post-merge proof for exact merged SHA, real routing, Dokploy, GHCR, and provider wiring. |
| `Staging AI/OCR Gate` | `26140468725`, `26139861002`, `26100318347` | `26099478674`, `26099042516`, `26097549636` | The gate is sparse and provider-backed. It should stay narrow because it spends external quota and validates provider realism after deterministic PR and staging proof. |
| `Production Release` | `26636834757`, `26636314940`, `26635994623` | `26636451107`, `26632124221`, `26631695544` | Failures were release/deploy integrity issues such as stale version health mismatch, which is appropriate for production. Production should not become the first business-correctness proof. |

Balance conclusion:

- delivery-speed balance: local and PR stay fast because deterministic work runs
  in parallel after classification, PR preview is deploy-relevant only, staging
  consumes successful `main` SHAs, and production promotes previously validated
  images.
- end-to-end consistency: version/SHA checks connect PR images, preview URLs,
  staging image promotion, and production release health so stale deployments
  cannot silently satisfy a newer gate.
- quality fallback: PR `finish` remains the merge authority for deterministic
  behavior, staging proves real infrastructure/provider paths, and production
  proves release integrity and availability only.

resource leak candidates:

- PR preview Dokploy compose, network, container, and volume leftovers when PRs
  close, deploy creation fails before a deployment record, or GitHub cleanup is
  cancelled.
- Legacy GHCR PR images and SHA images when preview branches churn quickly.
- Docker build cache and stopped containers on the Dokploy host after repeated
  image build, redeploy, or failed rollout loops.
- stale staging or production routes/images where health reports an older SHA or
  version, as seen in release failure logs. Classification and closure proof
  stay in [runtime-incident-response.md](../ssot/runtime-incident-response.md).
- Provider-backed runs that retry externally visible OCR/LLM work without tight
  path gating or isolated users.

### Resource leak hardening bundle

This follow-up is intentionally one PR because the controls are operationally
coupled but do not require a topology rewrite:

- PR preview leftovers: closed-PR cleanup still deletes the Dokploy compose on
  PR close, while closed-PR Dokploy reconciliation in the scheduled cleanup
  reconciles Dokploy preview composes against open PRs every six hours. When a
  newly created preview compose accepts deploy and redeploy requests but never
  creates a deployment record, the lifecycle deletes that empty compose shell,
  recreates it once, and still fails before readiness if the recreated compose
  cannot produce a deployment record.
  Host-level Docker leftovers remain owned by the
  `finance-report-vps-host-hygiene` Dokploy server schedule instead of GitHub
  Actions SSH.
- GHCR PR tag accumulation: the current PR preview workflow no longer creates
  or deletes PR image tags on close; scheduled cleanup prunes legacy closed-PR PR preview GHCR tags older than 14 days while preserving tags for open PRs.
- stale staging or production routes: staging already records before-SHA,
  image build, deploy, E2E, failed step, and failure-domain context. Production
  deploy context now records `production_before_version`, deploy-health
  outcome, smoke outcomes, and a production failure domain so stale version
  mismatches are diagnosable without turning production into the first
  correctness proof. Incident classification and stability proof stay in
  [runtime-incident-response.md](../ssot/runtime-incident-response.md).
- provider-backed external-state residue: staging AI/OCR remains gated by the
  structured provider relevance output and records
  `isolated-users-provider-gate-only`; the contract test rejects shared mutable
  user fixtures before provider-backed replay.
- Docker build cache and stopped containers: generic host garbage is still
  pruned by the Dokploy schedule, including stopped non-preview containers,
  build cache, old unused images, unused networks, oversized Docker json logs,
  and journal retention.

The speed boundary is unchanged: PR remains the deterministic merge authority,
PR Preview proves runtime/image/route/version and provider-free behavior,
staging proves merged-SHA infrastructure/provider realism, and production proves
release integrity plus health. The quality fallback improves because each leak
path now has either cleanup or failure context attached to the narrowest stage
that owns it.

safe simplification boundary: workflow consumers already read the structured
Env x Stage matrix, so the next real code reduction is to remove legacy scalar
classifier outputs only after external ad hoc consumers and required-check
configuration are confirmed. Image-build topology can also be simplified by
splitting backend and frontend builds into separate jobs, but that is a separate
branch-protection and GHCR-cache change.

### Coveralls reporting split

Implemented in PR #627. Pull requests no longer call Coveralls, and main pushes
upload only the unified line-only LCOV report for badge/trend reporting. Local
deterministic coverage gates remain the required merge/deploy boundary.

Risk: dashboard/badge freshness depends on successful main CI runs instead of PR
uploads.

### parallel image build jobs

Split backend and frontend SHA image builds into separate jobs or a matrix. The
latest observed frontend image build dominated the image-build job, while the
backend image was much shorter. Parallel jobs would make the bottleneck visible
and may shorten the normal main-push path.

Risk: GHCR tagging and cache behavior must remain identical for PR dry-runs and
main pushes.

## Out of scope for this PR

- Changing branch-protection required contexts.
- Reworking Docker image build topology.
- Removing legacy scalar change-classifier outputs before all workflows consume
  the structured Env x Stage matrix.

## Implemented follow-ups

### workflow_run staging trigger

- `workflow_run` staging trigger: automatic staging now starts only after the
  matching main CI workflow succeeds, checks out `workflow_run.head_sha`, and no
  longer waits for CI inside the deploy job.

### Coveralls status publication removal

- Coveralls status publication was removed from the required CI job. The active
  repository ruleset requires `finish`, not external Coveralls contexts, so local
  deterministic gates remain the merge/deploy boundary without synthetic status
  overrides.
