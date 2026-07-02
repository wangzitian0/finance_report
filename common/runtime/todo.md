# `runtime` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md). Each item becomes a `roadmap` AC in
[`contract.py`](./contract.py) — pinned to a real test — when the enforcement
invariants land (TDD).

## Done (the construct → switch → cleanup migration)

- [x] Package created on the model: `readme.md` + `contract.py` + `todo.md`,
      governed by `check_package_contract` as a `draft` `kernel` leaf.
- [x] **Manifest (base)** — `DependencyManifest` declares the external
      dependencies (database, object_storage, llm, cache, workflow_engine,
      telemetry, analytics, market_data) with their `Kind` and required tiers.
- [x] **Port + adapters** — `DependencyCheck` port + `ProbeResult`; the
      `DatabaseCheck` / `ObjectStorageCheck` / `LlmCheck` adapters own the probe
      logic; `boot.Bootloader` delegates to them.
- [x] **Drop `skipped`** — an absent declared dependency is now an `error`, not a
      silent `skipped` (runtime invariant 2), starting with the AI provider.

## Next (declared-required enforcement — a future feature, not the migration)

- [ ] **Env tier + manifest-driven validate.** Resolve the running `EnvTier`;
      `boot.validate` / the smoke test iterate `DEPENDENCY_MANIFEST.required_for`
      and fail on any declared-required dependency that is absent (invariant 2 for
      all deps, not just the AI provider).
- [ ] **Smoke ↔ declaration parity** (invariant 6) + the tag→staging-smoke gate.
- [ ] **Substitutes** (invariants 4/5): S3 → in-memory (moto), the real
      `StorageService` runs in CI (see #1520); LLM recording input-keyed.
- [ ] **Guardrail**: a new external dependency in `config.py` without a manifest
      entry fails CI.
- [ ] Promote `status` `draft` → `active` once the enforcement invariants land
      with tests, and add their roadmap ACs.

## Notes

- The compose files (`docker-compose*.yml`), `tools/infra.sh`, and the dev
  lifecycle stay at their functional locations (where docker compose / CI expect
  them); `runtime` owns them *conceptually* via the manifest, not by a physical
  move into the Python package.
