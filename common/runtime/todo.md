# `runtime` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md). Each item becomes a `roadmap` AC in
[`contract.py`](./contract.py) — pinned to a real test — when the enforcement
invariants land (TDD).

## Done (the construct → switch → cleanup migration, was #1554)

- [x] Package created on the model: `readme.md` + `contract.py` + `todo.md`,
      governed by `check_package_contract` as a `kernel` leaf (then-klass, since retired).
- [x] **Manifest (base)** — `DependencyManifest` declares the external
      dependencies (database, object_storage, llm, cache, workflow_engine,
      telemetry, analytics, market_data) with their `Kind` and required tiers.
- [x] **Port + adapters** — `DependencyCheck` port + `ProbeResult`; the
      `DatabaseCheck` / `ObjectStorageCheck` / `LlmCheck` adapters own the probe
      logic; `boot.Bootloader` delegates to them.
- [x] **Drop `skipped`** — an absent declared dependency is now an `error`, not a
      silent `skipped` (runtime invariant 2), starting with the AI provider.
- [x] **Status `draft` → `active`** with the smoke/health ACs homed in
      [`contract.py`](./contract.py)'s roadmap (`AC-runtime.1.*` / `AC-runtime.7.*`,
      #1554 Step 2).
- [x] **SSOT internalized** — `docs/ssot/env_smoke_test.md` retired; the Three
      Gates live in [`readme.md`](./readme.md), locked by
      `tests/tooling/test_runtime_ssot_internalized.py` (#1554 Step 3, #1569).

## Next (declared-required enforcement — a future feature, not the migration)

- [x] **#1577 — Env tier + manifest-driven validate.** Shipped as
      `resolve_env_tier` (ENVIRONMENT → `EnvTier`, unknown → strictest) +
      `Bootloader._required_checks(tier)`: FULL mode derives its dependency set
      from `DEPENDENCY_MANIFEST.required_for(tier)` (AC-runtime.3.1) — absent
      probed dependency fails; declared-required without a probe is a visible
      warning pending #1580. CRITICAL keeps its Gate-2 (DB-only) semantics.
- [x] **#1578 — Smoke ↔ declaration parity** (invariant 6). Shipped as
      `GET /health?full=1` — manifest-driven presence assertion for the running
      tier, called by `tools/smoke_test.sh` (AC-runtime.6.1); the
      tag→production gate already required the staging smoke
      (`release.yml` verifies a successful staging deploy on the tag).
- [x] **Substitutes** (invariants 4/5):
  - [x] **#1520** — the real `StorageService`/boto3 runs in the fast path
        against moto's in-memory S3 (upload → byte-identical read-back, plus
        the retry load-back leg — which caught a live reparse storage-key bug).
        Owned by EPIC-008 as AC8.26.1–.2
        (`tests/api/test_real_storage_pipeline.py`, #1601); runtime invariant 4
        delegates to those proofs. `DummyStorage` unit tests stay for cheap
        router edge cases.
  - [x] **#1581** — already input-keyed by construction: the cassette
        fingerprint is sha256(role + messages + decode params)
        (`src/llm/cassette.py::fingerprint`), and a replay miss is a hard
        failure — owned by the llm package as `AC-llm.6.2` (runtime invariant 5
        delegates to that proof; a duplicate runtime AC would be drift).
- [x] **#1579 — Guardrail**: a new external-dependency env var in `config.py`
      without a manifest entry fails CI. Shipped as
      `base/env_classification.py` (`check_env_classification` +
      `NON_DEPENDENCY_ENV_FIELDS`, AC-runtime.2.1): every `Settings` field is
      either a declared dependency env var or a reasoned non-dependency entry —
      fail-closed. Also surfaced + declared the stray `S3_PUBLIC_*` vars under
      `object_storage`.
- [x] **#1580 — Probes for the 5 declared-but-unprobed dependencies**: cache
      (Redis, raw TCP PING), workflow_engine (Prefect `/health`), telemetry
      (OTLP TCP connect), analytics (OpenPanel HTTP), market_data (Yahoo HTTP)
      each have a `DependencyCheck` adapter wired into
      `Bootloader._required_checks` (AC-runtime.4.1) — invariant 2 is now
      enforceable for the whole manifest. Also corrected two over-declarations:
      `cache` and the REAL `llm` provider are staging/prod requirements
      (preview has no Redis; CI/preview run the cassette substitute).

## Convergence snapshot (per dependency)

Point-in-time view of how far the boundary is actually enforced; the rows
change as the issues above land. "Call-site convergence" = the app talks to the
backend through one owned module, not scattered clients.

| Dependency | Manifest | Probe adapter | Call-site convergence | CI/local substitute | Gap |
|---|---|---|---|---|---|
| Postgres (`database`) | ✅ all 6 tiers | ✅ `DatabaseCheck` | ✅ `create_engine` only in `apps/backend/src/database.py` | real Postgres container (sqlite is a config-contract escape hatch only) | — |
| S3 (`object_storage`) | ✅ all 6 tiers | ✅ `ObjectStorageCheck` | ✅ boto3 only in `apps/backend/src/services/storage.py`; callers (e.g. `extraction/_media.py`) go through it | minio in compose; real `StorageService` pipeline vs moto in-memory S3 (#1520, AC8.26.1–.2); `DummyStorage` remains for cheap router edge cases only | — |
| LLM (`llm`) | ✅ model-dominant, real on staging/prod | ✅ `LlmCheck`, no `skipped` | ✅ `src/llm/` (client + cassette) | input-keyed cassette replay in CI/preview (AC-llm.6.2), real provider on staging/prod | — |
| Redis (`cache`) | ✅ staging/prod | ✅ `RedisCheck` (TCP PING) | — | — | — |
| Prefect (`workflow_engine`) | ✅ staging/prod | ✅ `WorkflowEngineCheck` | in-process fallback in app-owned tiers | — | — |
| OTel (`telemetry`) | ✅ VPS tiers | ✅ `TelemetryCheck` | ✅ `src/observability/` | — | — |
| OpenPanel (`analytics`) | ✅ staging/prod | ✅ `AnalyticsCheck` | ✅ `src/observability/`; frontend via `lib/api.ts` | — | — |
| Yahoo (`market_data`) | ✅ prod only | ✅ `MarketDataCheck` | ✅ `services/market_data/` | — | — |

Cross-cutting: every enforcement invariant is now wired — `boot.validate` FULL
is manifest-driven (#1577), the config↔manifest guardrail is fail-closed
(#1579), every declared dependency has a probe (#1580), the smoke asserts the
declared set via `/health?full=1` (#1578), and the substitutes fake the backend,
never the adapter (#1520 moto — AC8.26.*, #1581 input-keyed cassette — AC-llm.6.2). The remaining
declared-but-unprobed state can only reappear if a manifest entry lands before
its probe — `test_every_tier_declaration_is_smoke_assertable` fails in that
case.

## Notes

- The compose files (`docker-compose*.yml`), `tools/infra.sh`, and the dev
  lifecycle stay at their functional locations (where docker compose / CI expect
  them); `runtime` owns them *conceptually* via the manifest, not by a physical
  move into the Python package.
