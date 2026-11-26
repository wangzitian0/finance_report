# `runtime` — External Dependency Boundary

Owns dependency declarations (`DependencyManifest` from `infra2_sdk.service`), fail-closed probes (`DependencyCheck` / `ProbeResult` from `infra2_sdk.service`), and CD release coordinates/freshness (`sdk_pin.py`). CI test-selection stays in [common/testing/readme.md](../testing/readme.md).

## Invariants

1. **Declared => asserted**: Every declared dependency per `EnvironmentTier` has a check, substitute (`code-dominant` light substitute vs `model-dominant` input-keyed CI recording / real staging check), and smoke assertion.
2. **Absent => fail**: Missing declared dependencies fail `/health` (503) and smoke checks; no `skipped` fallback.
3. **Prod-required => SLA-bearing**: `DEPENDENCY_MANIFEST.required_for(EnvironmentTier.PRODUCTION)` declares mandatory production probes independently of feature flags.
4. **One env name per field**: No `Settings` field declares an alias chain, so an empty value cannot shadow another name (`tests/tooling/test_runtime_and_env_contracts.py::test_AC_runtime_guard_proofs_12_to_14_vault_producers_aliases_and_sensitivity`).
5. **SDK pin stays in this repository**: `install-infra2-sdk` runs `tools/sdk_pin.py` before the SDK is installed, so the reader uses only the standard library (`tests/tooling/test_runtime_and_env_contracts.py::test_AC_runtime_sdk_pin_1_agreement_stdlib_cli_and_errors`). infra2-sdk has no replacement (wangzitian0/infra2-sdk#241 dropped Slice 1).

## Background Jobs Manifest (`BACKGROUND_JOBS`)

`apps/backend/src/runtime/base/jobs.py` defines `BACKGROUND_JOBS` as the single registry for background loops and CLI triggers.
- Each `BackgroundJobSpec` declares `name`, `cli_name`, `concurrency`, `failure_metric`, and `summary`.
- `apps/backend/src/main.py` starts every registered loop in `lifespan` and exposes `run_background_job_once(cli_name)`.
- `python -m common.runtime.dev.cli job --list` lists registered jobs and `python -m common.runtime.dev.cli job --run-once <cli_name>` executes one pass.
- `RedisCheck.probe()` uses authenticated `redis.asyncio.from_url(...).ping()` with secret redaction on failures.
- `ObjectStorageCheck.probe()` checks primary S3, `S3_PUBLIC_*` when set, and an ephemeral put/delete check on `EnvironmentTier.STAGING` only.
- `LlmCheck.probe()` verifies provider HTTP reachability and Bearer auth on `/models` (or `/chat/completions` when `/models` returns 404/405).
- `TelemetryCheck.probe()` posts empty OTLP JSON to `/v1/traces` for HTTP(S) endpoints and uses TCP connect only for schemeless host:port targets.
- `AnalyticsCheck.probe()` requires `OPENPANEL_CLIENT_ID` and verifies `ready: true` on OpenPanel `/healthcheck`.
- `market_data` is required in both `EnvironmentTier.STAGING` and `EnvironmentTier.PRODUCTION`.

## Environment verification (the Three Gates)

`apps/backend/src/boot.py` runs one engine across three modes:
1. **Static (`dry-run`)**: Config/manifest integrity in CI/build.
2. **Startup (`critical`)**: DB connectivity, schema check, and protected-runtime secret validation on app boot (`sys.exit(1)` on failure).
3. **Health (`full`)**: Full dependency probes (`Redis`, `S3`, `LLM`) via `/health` and external `common/runtime/shell/smoke_test.sh`. Triage: [runtime-incident-response.md](./runtime-incident-response.md).
