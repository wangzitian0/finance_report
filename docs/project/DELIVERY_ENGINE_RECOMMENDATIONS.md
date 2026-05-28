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
| Unified coverage job | 1m 40s | Local coverage gates plus reporting-only Coveralls uploads |
| Staging post-merge lane | 18m 04s | Same-SHA CI wait, then deploy and E2E |
| Staging AI/OCR gate | 3m 53s | Provider-backed E2E execution |

## Recommended follow-ups

### Coveralls reporting split

Keep local deterministic coverage gates required. Coveralls uploads can remain
in the required job while they are fast and `continue-on-error`; move them to a
non-required reporting job only if upload latency becomes a repeated bottleneck.

Risk: dashboard/badge freshness must remain acceptable if uploads are moved out
of the required path.

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
