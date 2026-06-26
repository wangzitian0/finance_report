# App / Infra Contract Boundary (Infra-014)

> **Scope**: governs how this repo (the **App** / software) relates to **infra2**
> (the **runtime**) for environment and observability configuration.

## The rule

**infra2 = runtime; this repo = software.** infra2 **owns and issues** the
env/observability **contract**; the App **consumes** it and **fast-fails** when a
required value is missing. The App must **NOT re-define environments or the
observability contract**.

## infra2 owns + issues (do not restate or hardcode here)

- the environment **taxonomy** (names, suffixes, domains);
- the single **no-suffix OTLP collector** endpoint (the observability backend is a single global
  `prod_only` instance — there is no per-env collector);
- the layered **telemetry identity** — underlying short-commit-SHA
  `service.version` + surface `deployment.environment` alias (`production` /
  `staging` / `pr-<N>` / `commit-<sha>` / `tag-<x>` / `main`) and its allowed
  values;
- OpenPanel per-environment **client ids**.

## The App consumes (and only consumes)

- `apps/backend/src/config.py` reads `OTEL_*` and analytics env vars by
  `validation_alias` and **fast-fails** in deployed environments when a required
  value is missing.
- The App must **not** enumerate per-environment collector endpoints or
  `deployment.environment` values, and must **not** maintain an
  `openpanel_clients` map in `config.py` (that map lives in infra2's deploy
  tooling).

## Canonical contract (infra2, vendored at `repo/`)

- [`repo/docs/ssot/ops.observability.md`](../../repo/docs/ssot/ops.observability.md)
- [`repo/docs/ssot/core.environments.md`](../../repo/docs/ssot/core.environments.md) — see the *Telemetry identity* section.

## App-side consumption docs (pointers only, not the contract)

- [`docs/ssot/observability.md`](../ssot/observability.md)
- [`docs/ssot/environments.md`](../ssot/environments.md)

## Anti-regression guard

`tests/tooling/test_env_contract_boundary.py` fails if this repo re-grows the
contract (missing pointers, drift patterns, or a hardcoded `openpanel_clients`
map in `config.py`).
