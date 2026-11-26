<a id="package-model"></a>
# Package model — a package is a DDD bounded context

SSOT for package structure, five-layer DAG topology (`meta < infra < middleware < domain < app`), and business user-case governance.

## What a package is

Each package under `common/<pkg>/` contains `readme.md` documenting its ubiquitous language (`todo.md` is forbidden). Implementations live under `apps/backend/src/<pkg>/` and `apps/frontend/src/lib/<pkg>/`, converging into `base` (pure), `extension` (impure adapters/ports), and `data` (read projections).

## Five-layer topology

`PACKAGE_LAYER` (`common/meta/base/layering.py`) assigns every package to `meta` (L0), `infra` (L1), `middleware` (L2), `domain` (L3), or `app` (L4). `common.meta.extension.check_app_boundary`, `common.meta.extension.check_base_purity`, and `common.meta.extension.check_tier_imports` enforce layering, purity, and deterministic-core isolation. End-to-end business journeys live in [`common/meta/flows/user_cases_ssot.json`](./flows/user_cases_ssot.json).

See: [`migration-standard.md`](./migration-standard.md) · [`../../vision.md`](../../vision.md) · [`../../docs/project/traceability-exceptions.md`](../../docs/project/traceability-exceptions.md)
