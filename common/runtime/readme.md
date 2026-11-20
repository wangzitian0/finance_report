# `runtime` — External Dependency Boundary

Owns dependency declarations (`DependencyManifest`), fail-closed probes (`DependencyCheck` / `ProbeResult` from `infra2_sdk.runtime.health`), and CD release coordinates/freshness (`sdk_pin.py`, `github_api.py`). CI test-selection stays in [common/testing/readme.md](../testing/readme.md).

## Invariants

1. **Declared => asserted**: Every declared dependency per `EnvTier` has a check, substitute (`code-dominant` light substitute vs `model-dominant` input-keyed CI recording / real staging check), and smoke assertion.
2. **Absent => fail**: Missing declared dependencies fail `/health` (503) and smoke checks; no `skipped` fallback.
3. **Prod-required => SLA-bearing**: `DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION)` declares mandatory production probes independently of feature flags.
4. **Empty env vars are values**: Shipped `.env.example` / compose files must not assign empty values in `AliasChoices` chains (`tests/tooling/test_env_empty_value_producers.py`).

## Background Jobs Manifest (`BACKGROUND_JOBS`)

`apps/backend/src/runtime/base/jobs.py` defines `BACKGROUND_JOBS` as the single registry for background loops and CLI triggers.
- Each `BackgroundJobSpec` declares `name`, `cli_name`, `concurrency`, `failure_metric`, and `summary`.
- `apps/backend/src/main.py` starts every registered loop in `lifespan` and exposes `run_background_job_once(cli_name)`.
- `python tools/cli.py job --list` lists registered jobs and `python tools/cli.py job --run-once <cli_name>` executes one pass.
- `RedisCheck.probe()` uses authenticated `redis.asyncio.from_url(...).ping()` with secret redaction on failures.

## Environment verification (the Three Gates)

`apps/backend/src/boot.py` runs one engine across three modes:
1. **Static (`dry-run`)**: Config/manifest integrity in CI/build.
2. **Startup (`critical`)**: DB connectivity, schema check, and protected-runtime secret validation on app boot (`sys.exit(1)` on failure).
3. **Health (`full`)**: Full dependency probes (`Redis`, `S3`, `LLM`) via `/health` and external `tools/smoke_test.sh`. Triage: [runtime-incident-response.md](./runtime-incident-response.md).
