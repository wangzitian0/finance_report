# Delivery Engine Recommendations

> Owner: EPIC-008 testing strategy | See: [common/testing/ci-cd.md](../../common/testing/ci-cd.md)

CI and post-merge optimization evidence and follow-ups outside routine SSOT edits.

## Current baseline

- **2026-09-16**: Backend shards refreshed via `ci/backend-test-durations.json` and moved to 8-way split (`AC-testing.ci-structure.8`).
- **2026-06-21 (#1252 closure readout, PR #1288 `ab2630e1`)**: Main CI heavy path `4m 46s`; slowest backend shard 3/5 in run `27896401849` (`3m 50s`; all 5 shards: `3m 31s / 3m 43s / 3m 49s / 3m 50s / 3m 41s`). **Do not add more shards** until timing evidence shows backend tail regression.

## Recommended follow-ups

### Structured matrix consumer migration

`common/testing/change_classifier.py` emits structured Env x Stage outputs (`env_stage_required`, `env_stage_reasons`, `env_stage_stages`, `env_stage_files`) consumed directly by GitHub Actions jobs now (after retiring `legacy scalar outputs` / `compatibility shims` and leaving `branch protection` keyed on job names across `CI`, `PR Test Environment`, `Deploy Staging`, `Staging AI/OCR Gate`, and `Production Release`).

### Sparse matrix evidence audit

June 9, 2026 evidence sample (three newest successful vs failed runs):

| Lane | Successful samples | Failed samples |
|---|---|---|
| `CI` | `27186502313`, `27183789200`, `27183466331` | `27184608585`, `27183552389`, `27183418593` |
| `PR Test Environment` | `27186502312`, `27183466349`, `27183418552` | `27184608593`, `27183789205`, `27183223104` |
| `Deploy Staging` | `27182443187`, `27150045338`, `27135967250` | `27136569205`, `27133497263`, `27115009456` |
| `Staging AI/OCR Gate` | `26140468725`, `26139861002`, `26100318347` | `26099478674`, `26099042516`, `26097549636` |
| `Production Release` | `26636834757`, `26636314940`, `26635994623` | `26636451107`, `26632124221`, `26631695544` |

Identified **resource leak candidates**: GHCR PR images, Docker build cache, and stale staging or production routes (see [runtime-incident-response.md](../../common/runtime/runtime-incident-response.md)), defining a safe simplification boundary.

### Resource leak hardening bundle

Delivered as one PR: host Docker cleanup via `finance-report-vps-host-hygiene` schedule; pruning legacy closed-PR GHCR tags (>14d); recording `production_before_version`; enforcing `isolated-users-provider-gate-only` for staging AI/OCR.

### Coveralls reporting split & workflow_run staging trigger & parallel image build jobs

- **Coveralls reporting split**: PRs skip Coveralls; `main` uploads line-only LCOV (status publication removed).
- **workflow_run staging trigger**: Staging runs after matching main CI succeeds.
- **parallel image build jobs**: Separate backend and frontend image builds remain a candidate follow-up.

## Out of scope for this PR

- Changing branch-protection required contexts or Docker image build topology.
