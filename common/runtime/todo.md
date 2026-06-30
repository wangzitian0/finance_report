# `runtime` — todo

The package-local worklist. Cross-package migration lives in
[`../todo.md`](../todo.md). Each item below becomes a `roadmap` AC in
[`contract.py`](./contract.py) — pinned to a real test — when it lands (TDD: a
failing test first).

## Done

- [x] Package created on the model: ships `readme.md` + `contract.py` + `todo.md`,
      governed by `check_package_contract` as a `draft` `kernel` leaf
      (`depends_on=[]`, `interface=[]`).

## Next (the dependency-boundary contract, in order)

- [ ] **Manifest (base).** Define `DependencyManifest`: per env tier, the declared
      required dependencies + each one's `Kind`. First filled from a full audit of
      `config.py` (S3, LLM, Postgres, Redis, Prefect, OTel, OpenPanel, market-data).
- [ ] **Port (base).** Lift `ServiceStatus` + the `_check_*` methods out of
      `boot.py` into a `DependencyCheck` port + per-dependency adapters
      (extension). Drop the `"skipped"` status (invariant 2).
- [ ] **Assert + fail (api).** `boot.validate` + `smoke_test` assert the declared
      set for their tier; a declared-but-absent dependency fails (no `warning`).
      Proof: dropping a declared dependency's config makes the smoke FAIL.
- [ ] **Smoke ↔ declaration parity.** Extend the smoke meta-guard to
      `checks == declared count`; wire the tag→staging smoke as the prod-promote
      gate.
- [ ] **code-dominant substitutes.** S3 → in-memory (moto) so the real
      `StorageService` runs in CI (retire `DummyStorage`); the upload→store→load→
      parse pipeline test. Redis → fakeredis or document the in-memory path.
      Market-data → transport-layer record/replay (not a blanket disable).
- [ ] **model-dominant recording.** Pin the LLM recording as input-keyed (changed
      input ⇒ miss); the staging gate (real provider) stays recording-free.
- [ ] **Guardrail.** A contract test: adding an external dependency to `config.py`
      without (kind + per-tier declaration + substitute + smoke assertion) fails CI.
- [ ] Promote `status` `draft` → `active` once the manifest + port + assert
      invariants have landing tests.
