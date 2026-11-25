# CI/CD and Test Optimization SSOT — Deploy Half

> **SSOT Key**: `ci-cd` (deploy half) | Post-merge staging/production deploy and E2E gates. Test pipeline: [common/testing/ci-cd.md](../testing/ci-cd.md).

## Deploy Implementation

- **Manual staging & promote-not-rebuild**: `main` CI pushes immutable `:<sha7>` images; `ci.yml` (`promote-release-images`) copies them to `:vX.Y.Z` on tag push. `infra2` dispatches `deploy_v2` manually (`workflow_dispatch`) and invokes `runtime-hooks.manifest.json` (`smoke`, `preview_gate`, `staging_gate`, `scheduled_audit`).
- **Concurrency & parallel staging**: Manual staging dispatches serialize on `staging-deploy`; bypassing the serial bottleneck via `parallel staging` uses separate staging stacks.
- **Fail-closed release coordinates**: `infra2-sdk` release coordinates pin exact `version_ref` tags; `tools/verify_release_images.py` checks backend/frontend digests; `boot.py` and `verify_effective_config_hash` prevent stale config deploys.
- **AI/OCR Canary vs Audit Replay**:
  - `AI/OCR Canary` (`corpus: canary` in `staging_gate`): runs `tests/e2e/test_brokerage_upload_to_portfolio_value.py` against the deployed VPS (`glm-5.3-flash`) after `Staging Provider Gate` passes (4xx fails hard; 5xx/timeout degrades).
  - `Audit Replay` (`corpus: audit_replay` / `core_journey` in `scheduled_audit`; `audit-replay.yml` deleted in #2831): `audit_replay` runs all non-canary live-LLM journeys and `core_journey` runs the disjoint non-LLM `CORE_JOURNEY_ONLY_FILES` journeys asynchronously without blocking production promotion.
- **Honest deploy smoke**: `common/runtime/shell/smoke_test.sh` probes `/api/health?full=1` (asserting `git_sha`, `database`, `object_storage`, all required checks, and `market_data` on Staging) and branches by `MODE` (`prod` stays read-only; non-prod runs an unauthenticated `POST /api/auth/login` 401/429 round-trip).
- **Incident triage**: Owned by [runtime-incident-response.md](./runtime-incident-response.md). See [DELIVERY_ENGINE_RECOMMENDATIONS.md](../../docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md).
