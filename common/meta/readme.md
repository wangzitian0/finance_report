<a id="package-model"></a>
# Package model — a package is a DDD bounded context

SSOT for package structure, five-layer DAG topology (`meta < infra < middleware < domain < app`), and authority tiers (`common/meta/contract.py`).

## What a package is

Each package under `common/<pkg>/` contains `readme.md` (ubiquitous language; `todo.md` is forbidden) and `contract.py` (`CONTRACT = PackageContract(...)` declaring `status`, `units`, `depends_on`, `implementations`, `interface == __init__.__all__`, `invariants`, `roadmap` ACs, `concepts`). Implementations live under `apps/backend/src/<pkg>/` and `apps/frontend/src/lib/<pkg>/` converging into `base` (pure), `extension` (impure adapters/ports), and `data` (read projections).

## Five-layer topology

`PACKAGE_LAYER` (`common/meta/base/layering.py`) assigns every package to `meta` (L0), `infra` (L1), `middleware` (L2), `domain` (L3), or `app` (L4). `check_package_contract` enforces **never up, never sideways-cyclic** across `dependency_index(contracts)` computed by `common/meta/base/dependency_graph.py`. Governance is computed from contracts (`common/meta/extension/generate_ac_registry.py`, `MANIFEST.yaml` + `concepts`); temporary exceptions live in `common/meta/data/governance-exceptions.yaml` and drafts in `check_draft_packages`.

## Authority tiers

`PackageContract.tier` (`common/meta/base/authority_matrix.py`) records who produces the result and constrains valid `roadmap` `proof_kind`:
- `CODE-ONLY`: deterministic code; exact/property proof; must not import LLM modules (`tools/check_tier_imports.py`).
- `CODE-LED`: deterministic code with LLM knobs; assert code decision.
- `LLM-LED`: LLM emits, code validates via deterministic oracle; invariant/property/eval proof, **never exact-golden**.
- `LLM-ONLY`: narrative LLM output with no financial writes; smoke/eval proof.

Structural checks belong in `invariants`, not `roadmap`. `common/meta/extension/authority_classifier.py` computes actual `CODE`/`LLM` shares from test shapes (`BANDS`), reconciled by `tools/check_authority_reconcile.py`.

See: [`migration-standard.md`](./migration-standard.md) · [`../../vision.md`](../../vision.md) · [`../../docs/project/traceability-exceptions.md`](../../docs/project/traceability-exceptions.md)
