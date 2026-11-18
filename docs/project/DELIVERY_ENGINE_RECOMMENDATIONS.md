# Delivery Engine Recommendations

> Owner: EPIC-008 testing strategy | See: [common/testing/ci-cd.md](../../common/testing/ci-cd.md)

CI and post-merge optimization baseline outside routine SSOT edits.

## Current baseline

- **2026-09-16**: Backend shards refreshed via `ci/backend-test-durations.json` and moved to 8-way split (`AC-testing.ci-structure.8`).
- **2026-06-21 (#1252 closure readout, PR #1288 `ab2630e1`)**: Main CI heavy path `4m 46s`. **Do not add more shards** until timing evidence shows backend tail regression.
- **Matrix & resource hygiene**: `common/testing/change_classifier.py` drives GitHub Actions directly (`env_stage_required`, `env_stage_reasons`, `env_stage_stages`, `env_stage_files`). Docker/GHCR host hygiene and stale route cleanup live in [runtime-incident-response.md](../../common/runtime/runtime-incident-response.md). Coverage policy (post-#2934 Wave A retirement of Coveralls/diff-coverage) lives in [common/testing/coverage.md](../../common/testing/coverage.md).

## Open candidate follow-ups

- **Parallel image build jobs**: Separate backend and frontend image builds remain a candidate follow-up (`workflow_run` deploys staging after matching `main` CI succeeds).
