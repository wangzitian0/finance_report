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
| Unified coverage job | 3m 36s | Coveralls reporting-only status normalization |
| Staging post-merge lane | 18m 04s | Same-SHA CI wait, then deploy and E2E |
| Staging AI/OCR gate | 3m 53s | Provider-backed E2E execution |

## Recommended follow-ups

### Coveralls reporting split

Keep local deterministic coverage gates required, but move Coveralls upload and
status normalization into a non-required reporting job after unified coverage
passes. This should reduce the required CI critical path by roughly the time now
spent in `Mark Coveralls statuses reporting-only`, while preserving dashboards.

Risk: branch protection and existing Coveralls status contexts must be audited
before changing required checks.

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
- Reworking Docker image build topology.

## Implemented follow-ups

### workflow_run staging trigger

- `workflow_run` staging trigger: automatic staging now starts only after the
  matching main CI workflow succeeds, checks out `workflow_run.head_sha`, and no
  longer waits for CI inside the deploy job.
