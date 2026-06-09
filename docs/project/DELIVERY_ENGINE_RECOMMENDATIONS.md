# Delivery Engine Recommendations

> Owner: EPIC-008 testing strategy
> See: docs/ssot/ci-cd.md

This note captures CI and post-merge optimization items that should stay
separate from routine SSOT edits because they change workflow topology or
branch-protection behavior.

## Current baseline

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
- PR Preview is the noisiest deployed lane; recent failures concentrated in
  `Deploy preview lifecycle` before browser E2E, so it should stay scoped to
  runtime/API/UI preview-relevant paths.
- Staging is correctly acting as the post-merge environment gate; recent
  failures were split between Dokploy deploy health and application E2E, then
  surfaced through `Post-merge Delivery`.
- Provider-backed AI/OCR and production release checks are appropriately
  narrow. They prove provider or release integrity only after deterministic PR
  and staging proof exists.

The next code simplification should remove the scalar compatibility shims after
branch protection, required-check behavior, and any external ad hoc consumers
are confirmed to rely only on the structured consumers.

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
