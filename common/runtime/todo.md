# `runtime` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md). Each item becomes a `roadmap` AC in
[`contract.py`](./contract.py) — pinned to a real test — when the enforcement
invariants land (TDD).

## Done (the construct → switch → cleanup migration, was #1554)

- [x] Package created on the model: `readme.md` + `contract.py` + `todo.md`,
      governed by `check_package_contract` as a `kernel` leaf.
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

- [ ] **#1577 — Env tier + manifest-driven validate.** Resolve the running
      `EnvTier`; `boot.validate` / the smoke test iterate
      `DEPENDENCY_MANIFEST.required_for` and fail on any declared-required
      dependency that is absent (invariant 2 for all deps, not just the AI
      provider). `boot.py`'s per-mode dependency lists derive from the manifest.
- [ ] **#1578 — Smoke ↔ declaration parity** (invariant 6) + the
      tag→staging-smoke gate. Depends on #1577.
- [ ] **Substitutes** (invariants 4/5):
  - [ ] **#1520** — S3 → in-memory (moto); the real `StorageService` runs in CI
        (retire the `DummyStorage` wrapper stub).
  - [ ] **#1581** — LLM recording is input-keyed: changed input ⇒ recording
        miss, never a stale replay.
- [ ] **#1579 — Guardrail**: a new external-dependency env var in `config.py`
      without a manifest entry fails CI (declared-vs-actual reconciliation, same
      pattern as `check_pr_ci_evidence` / `check_package_directory_coverage`).
- [ ] **#1580 — Probes for the 5 declared-but-unprobed dependencies**: cache
      (Redis), workflow_engine (Prefect), telemetry (OTel), analytics
      (OpenPanel), market_data (Yahoo) each get a `DependencyCheck` adapter.

## Convergence snapshot (per dependency)

Point-in-time view of how far the boundary is actually enforced; the rows
change as the issues above land. "Call-site convergence" = the app talks to the
backend through one owned module, not scattered clients.

| Dependency | Manifest | Probe adapter | Call-site convergence | CI/local substitute | Gap |
|---|---|---|---|---|---|
| Postgres (`database`) | ✅ all 6 tiers | ✅ `DatabaseCheck` | ✅ `create_engine` only in `apps/backend/src/database.py` | real Postgres container (sqlite is a config-contract escape hatch only) | — |
| S3 (`object_storage`) | ✅ all 6 tiers | ✅ `ObjectStorageCheck` | ✅ boto3 only in `services/storage.py` + `extraction/_media.py` | minio in compose; unit tests still monkeypatch `DummyStorage` | #1520 (invariant 4) |
| LLM (`llm`) | ✅ model-dominant | ✅ `LlmCheck`, no `skipped` | ✅ `src/llm/` (client + cassette) | cassette replay in CI, real provider on staging | #1581 (input-keyed) |
| Redis (`cache`) | ✅ VPS tiers | ❌ | — | — | #1580 |
| Prefect (`workflow_engine`) | ✅ staging/prod | ❌ | in-process fallback in app-owned tiers | — | #1580 |
| OTel (`telemetry`) | ✅ VPS tiers | ❌ | ✅ `src/observability/` | — | #1580 |
| OpenPanel (`analytics`) | ✅ staging/prod | ❌ | ✅ `src/observability/`; frontend via `lib/api.ts` | — | #1580 |
| Yahoo (`market_data`) | ✅ prod only | ❌ | ✅ `services/market_data/` | — | #1580 |

Cross-cutting: enforcement is not yet manifest-driven (#1577), smoke parity is
unenforced (#1578), and nothing stops a new `config.py` dependency from
bypassing the manifest (#1579).

## Notes

- The compose files (`docker-compose*.yml`), `tools/infra.sh`, and the dev
  lifecycle stay at their functional locations (where docker compose / CI expect
  them); `runtime` owns them *conceptually* via the manifest, not by a physical
  move into the Python package.
