# Delivery Engine Recommendations

> Owner: EPIC-008 testing strategy
> See: docs/ssot/ci-cd.md

This note captures the CI and post-merge optimization items intentionally left
out of the narrow delivery-sync PR. The PR fixes local/CI drift and PR-preview
gate parity; the items below change workflow topology or branch-protection
behavior and should be handled as separate reviewed PRs.

## Current baseline

Observed on May 27, 2026:

| Lane | Recent duration | Main contributor |
|---|---:|---|
| Main CI heavy path | 8m 56s | Backend shard wall time plus unified coverage |
| Unified coverage job | 3m 36s | Coveralls reporting-only status normalization |
| Staging post-merge lane | 18m 04s | Waiting for same-SHA CI, then deploy and E2E |
| Staging AI/OCR gate | 3m 53s | Provider-backed E2E execution |

## Recommended follow-ups

### Coveralls reporting split

Keep local deterministic coverage gates required, but move Coveralls upload and
status normalization into a non-required reporting job after unified coverage
passes. This should reduce the required CI critical path by roughly the time now
spent in `Mark Coveralls statuses reporting-only`, while preserving dashboards.

Risk: branch protection and existing Coveralls status contexts must be audited
before changing required checks.

### workflow_run staging trigger

Replace the staging workflow's in-job wait for same-SHA CI with a `workflow_run`
trigger that starts staging only after the matching CI run succeeds. Keep manual
dispatch as a recovery path and keep the healthy-but-stale diagnostic for failed
or delayed CI.

Risk: GitHub Actions event semantics need careful testing so staging still
targets the exact merged SHA and does not deploy a stale or superseded commit.

### parallel image build jobs

Split backend and frontend SHA image builds into separate jobs or a matrix. The
latest observed frontend image build dominated the image-build job, while the
backend image was much shorter. Parallel jobs would make the bottleneck visible
and may shorten the normal main-push path.

Risk: GHCR tagging and cache behavior must remain identical for PR dry-runs and
main pushes.

## Out of scope for this PR

- Changing branch-protection required contexts.
- Moving Coveralls status publication out of the current required job.
- Replacing the staging push trigger with `workflow_run`.
- Reworking Docker image build topology.
