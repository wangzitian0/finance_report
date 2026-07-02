# `runtime` — the app↔external-world dependency boundary

> **Status: active.** The boundary — value language, manifest, `DependencyCheck`
> port + adapters — is shipped, and the smoke/health ACs are homed in
> [`contract.py`](./contract.py)'s roadmap. Remaining work (manifest-driven
> enforcement, substitutes) is tracked in [`todo.md`](./todo.md).
> Model spec: [`../meta/readme.md`](../meta/readme.md).

## Why this package exists

The application depends on external backends — object storage (S3), the LLM
provider, cache (Redis), telemetry (OTel), analytics (OpenPanel), the database.
Today that boundary is **homeless**: `ServiceStatus` + `_check_*` float in
`apps/backend/src/boot.py`, env keys live in `config`, the smoke test is a shell
script, and the six-environment tiering lives in `environments.md`. Nobody owns
the *contract* across them — which is exactly why dependencies **degrade
silently** (`_check_ai_provider` returns `"skipped"` when unconfigured; S3 is
treated as "optional" and only `warning`s when down).

`runtime` is the bounded context that owns that boundary: **what we depend on,
how each environment provides or substitutes it, and the guarantee that a
declared dependency is proven present — or the build/smoke fails.**

Scope note (#1556): `runtime` is a **domain package like any other** — its
domain happens to be environments/dependencies/**CD** (deploy execution,
release evidence, rollback, environment tiering). Cross-cutting CI governance
— which tests run where, and proof that they ran — belongs to
[`common/testing`](../testing/README.md); the responsibility split is defined
in that package's charter. In the failure-attribution table there: dependency
missing / env wrong / config drift → this package's contract; everything about
test selection, execution, and reporting → `testing`.

## Ubiquitous language

- **Dependency** — an external backend the app talks to across a process edge.
- **Kind** — how a dependency must be tested:
  - **code-dominant** (e.g. S3, Redis): deterministic; a light substitute behaves
    identically to the real backend, so it is behaviourally equivalent everywhere.
  - **model-dominant** (e.g. the LLM): non-deterministic; output depends on the
    real service. *Input changes ⇒ result changes* — so CI uses an **input-keyed
    recording**, and the real behaviour is validated only against staging.
- **Substitute** — the per-environment stand-in for a dependency. A *backend* may
  differ per environment (in-memory ≠ minio ≠ real S3); that is expected and fine.
- **Env tier** — one of the six environments (Local Dev / Local CI / GitHub CI /
  PR Preview / Staging / Production). CI and Preview use **light substitutes**
  (Preview = same as CI but persistent); Staging and Production use **real**
  backends.
- **Declared vs present** — each env *declares* its required dependencies (via env
  vars, owned with `config`); a dependency is either **present** or **absent** —
  there is no `skipped`.

## Invariants (the contract)

1. **Declared ⇒ asserted.** Every dependency an environment declares as required
   has a check, a substitute, and a smoke assertion.
2. **Absent ⇒ fail.** A declared dependency that is missing/unreachable fails
   `/health` and the smoke test. No silent `skipped` / `warning` / fallback.
3. **Substitute by tier.** CI/Preview run light substitutes; Staging/Production
   run real backends. The *backend* may differ per env; the *presence* must not.
4. **code-dominant ⇒ real adapter runs in CI.** The substitute fakes the
   *backend* (in-memory), never the app's own adapter — so the real adapter code
   executes in CI (no wrapper-stub like `DummyStorage`).
5. **model-dominant ⇒ recorded in CI, real on staging.** CI replays an
   input-keyed recording (changed input ⇒ recording miss); the real provider is
   exercised only by the staging gate (which does **not** read recordings).
6. **Smoke ↔ declaration parity.** The smoke test asserts exactly the declared set
   for its tier (count == declared count); a release tag promotes only after the
   **staging** smoke (real backends, real LLM) passes.

## Shape (port / adapter, per the `base`/`extension`/`data` model)

- **base** — the `DependencyCheck` port (the `ServiceStatus`/check protocol) + the
  **DependencyManifest** (declared required dependencies per env tier) + the value
  language (`Kind`, `EnvTier`, presence status — no `skipped`).
- **extension** — the per-dependency check/substitute adapters (db, s3, llm,
  redis, telemetry). Each implements the port; an adapter may instead live in its
  own domain package and implement this port (dependency inversion).
- **api** — `boot.validate` and the **environment smoke test**
  (`tools/smoke_test.sh`) are this package's boundary: `runtime` **owns** the
  smoke test — the deployed-environment verification that every declared
  dependency is present (invariants 2 and 6), plus the version-integrity /
  routing / functional checks it composes. See *Environment verification* below.

## Environment verification (the Three Gates)

One validation engine (`apps/backend/src/boot.py`) runs across all environments — "one
codebase, one standard" — at three gates of increasing strictness:

| Gate | Mode | When | Scope | Failure |
|------|------|------|-------|---------|
| **1 Static** | `dry-run` | build / CI | config integrity (keys present) + code importable | build / CI fail |
| **2 Startup** | `critical` | app start | database connectivity + schema/migration sync | crash-loop (refuse to serve) |
| **3 Health** | `full` | runtime | full stack (Redis, S3, AI) + latency | alert / 503 (drain traffic) |

Each environment maps to these gates with the same code: **Local** — Gate 2 on
`moon run :dev`, Gate 3 via `python -m src.boot --mode full`; **CI** — Gate 1
(`--mode dry-run`) + Gate 2 (pytest DB fixture); **Staging / Production** — Gate 2
at container entrypoint (`main.py`), Gate 3 via the load balancer hitting
`/health`. Two complementary checks: `src.boot` proves *internal connectivity*
("can the app reach its dependencies?"); `tools/smoke_test.sh` proves *external
availability* ("can a user reach the app?"). Deployed-service incident routing
(502/503, stale version, secrets, flapping) lives in
[`docs/ssot/runtime-incident-response.md`](../../docs/ssot/runtime-incident-response.md).

## Boundaries with neighbouring packages

- **`config`** — owns the env-var *mechanism*: the three-layer SSOT
  (`secrets.ctmpl` ↔ `config.py` ↔ `.env.example`), the pydantic `Settings`
  reader, and schema validation — shared by every package. `runtime` owns the
  *dependency layer* on top: the **manifest is the SSOT for which env vars are
  external-dependency env vars** (`Dependency.env_vars`, bound to `Settings`),
  each dependency's kind, its per-tier substitute, and the presence assertion.
  (Only dependency env vars consolidate here — feature/security/domain env vars
  stay with `config` and their domain packages.)
- **`testing`** — owns proof *provenance* (`deterministic` / `golden_fixture` /
  `live_llm`); `runtime`'s `Kind` maps onto it (code-dominant → deterministic,
  model-dominant → live on staging).
- **`platform`** — the *in-process* middleware substrate (event bus, rate limiter).
  `runtime` is the complementary *outbound* substrate (the edges to the external
  world). Distinct concerns; sibling kernels.
- **`observability`** — telemetry is itself a dependency `runtime` declares/asserts,
  but its own emit/query logic stays in `observability`.

## Public vs internal

The package publishes (`contract.interface`) the `base` value language + manifest
+ port and the `extension` adapters: `DependencyKind`, `EnvTier`
(+ `APP_OWNED_TIERS` / `VPS_TIERS`), `Dependency` / `DependencyManifest` /
`DEPENDENCY_MANIFEST`, the `DependencyCheck` port (+ `DependencyStatus` /
`ProbeResult`), and `DatabaseCheck` / `ObjectStorageCheck` / `LlmCheck`.
`boot.Bootloader` delegates its checks to the adapters. See [`todo.md`](./todo.md)
for the remaining enforcement work.
