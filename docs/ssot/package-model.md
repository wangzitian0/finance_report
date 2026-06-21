<a id="package-model"></a>

# Package model — a package is a DDD bounded context

> SSOT for **what a package is** and **how packages are governed**. This owns the
> *term* "package" and the contract every package speaks; it does not own any
> single package's goal (that is the package's README) or the product direction
> (vision.md). First worked example: [`apps/backend/src/counter`](../../apps/backend/src/counter/README.md);
> the prototype vertical slice is [`apps/backend/src/ledger`](../../apps/backend/src/ledger/ledger.contract.md).

## What a package is

A **package = a DDD bounded context**. It is the unit of ownership and
governance. Every package is exactly these parts:

1. **README** — prose: the *ubiquitous language*, why the package exists, a usage
   example, and what is public vs internal. (The module-slice axis.)
2. **`contract`** — a machine-checkable `PackageContract` (a pydantic model in
   `contract.py`): the package's published `interface`, emitted `events`, the
   `invariants` it guarantees, and its `roadmap` (the ACs it owns).
3. **Roles** — files converge by role, not by feature:
   - `types/` — domain **nouns** + events (the value language; pure, no I/O).
   - `ops/` — domain **verbs** (the edges in the project DAG; depend on a store
     *port*, never a concrete store or the ORM).
   - `store/` — persistence: a `Protocol` **port** + a concrete adapter (the only
     role that touches the ORM/session).
   - `api/` — the boundary (in-process verbs, or a thin transport adapter).
4. **Published language** — `__init__.__all__` is the *entire* public surface;
   everything else is internal. `contract.interface` must equal `__all__`.

## Three package classes

A package declares one `klass`; the class fixes its place in the dependency DAG
(dependencies point **down only**, never up, never sideways-cyclic):

| class | what it is | may depend on |
|-------|-----------|---------------|
| `kernel` | a leaf value language reused everywhere (e.g. `money`, `ratio`, `quantity`) | nothing in the app |
| `platform` | a reusable horizontal capability (e.g. `counter`) | `kernel` only |
| `core` | a vertical domain slice (e.g. `ledger`) | `platform` + `kernel` |

## Governance is computed, not authored

The only **authored horizontal doc is `vision.md`** (the "why"). Everything else
about a package is *derived from its contract*:

- `tools/check_package_contract.py` (logic in
  `common/governance/check_package_contract.py`) discovers every package by
  scanning `apps/backend/src/*/contract.py` for a `CONTRACT = PackageContract(...)`
  and asserts, per package:
  - **(a)** `contract.interface == __init__.__all__` (contract and published
    language agree);
  - **(b)** every `invariants[].test` and `roadmap[].test` (a `"path::func"`
    reference) resolves to a real test function (an unproven invariant is not an
    invariant);
  - **(c)** no module imports a **higher-class** registered package or an
    undeclared dependency (the DAG rule, mirroring
    `tests/tooling/test_ledger_module.py`).

Because governance reads the contract, adding a package adds no central index to
edit: a new package is governed the moment it ships a `contract.py`. A package's
ACs live in its `roadmap`; they are mirrored into an EPIC table only so the
existing AC-index gate stays green during the transition to the package model.

## Examples

- **`counter`** (`platform`) — the first full worked example: per-(user, key)
  tallies for insight reports. `CounterKey`/`Count` value objects (`types`),
  `increment`/`get_count` verbs (`ops`) over a `CounterRepository` port (`store`),
  a thin async `read_count` boundary (`api`), and a `PackageContract` whose
  `roadmap` owns `AC25.6.1`–`AC25.6.4`. See its
  [README](../../apps/backend/src/counter/README.md) and
  [`contract.py`](../../apps/backend/src/counter/contract.py).
- **`ledger`** (`core`) — the prototype vertical slice that introduced the
  role/DAG idea (`types`/`ops` with the balance invariant as a type). See
  [`ledger.contract.md`](../../apps/backend/src/ledger/ledger.contract.md). It
  predates `PackageContract`; it will adopt one as the model rolls out.
