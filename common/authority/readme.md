# authority — the CODE↔LLM authority-tier bounded context

> One package owning the whole authority-tier concept. The prose SSOT for the
> *meaning* of the tiers lives in
> [`docs/ssot/authority-tiers.md`](../../docs/ssot/authority-tiers.md); this
> package is the machine implementation + enforcement.

## What a tier is

Every acceptance criterion / package carries an **authority tier** — a
*module-design* property on one ordered CODE↔LLM spectrum (how much of the
output the LLM produces, and how tightly code constrains it):

| tier | who produces the result |
|------|-------------------------|
| `CODE-ONLY` | code, no LLM |
| `CODE-LED` | code; the LLM only assists within strict code constraints |
| `LLM-LED` | the LLM emits; code validates/guards, never produces |
| `LLM-ONLY` | the LLM emits, no validation |

(`HU` = "undecided" — a draft package with `tier=None`, not a permanent tier.)

## One vocabulary, two views

The same four-tier scale is used by both views, which is why they cannot drift:

- **declared** — `PackageContract.tier` (a package's authorial intent);
- **detected** — the band `authority_classifier` measures from the shapes of the
  tests that prove a package's ACs (`BANDS` *is* `PACKAGE_TIERS`).

## Structure (layers)

The **target** model — like every migrated package — is to converge by **layer**
(base / extension / data) rather than by role. `authority` is **not there yet**:
its `contract.py` still declares legacy `roles=["matrix", "classifier", "gates"]`
and the files are physically flat under `common/authority/`. The base/extension
split below is therefore the **conceptual/intended** layering each file maps onto;
the role-to-layer migration is still pending.

- **base** — the value language: `authority_matrix.py` (tier Literals, the
  tier→proof matrix, the canonical tuples; stdlib-only, no pydantic) and
  `authority_classifier.py` (the detected CODE/LLM band). Self-contained pure
  definitions + logic, no I/O.
- **extension** — the gates (run via `tools/<name>.py`): `check_ac_proof_kind`
  (tier→proof matrix), `check_tier_ast_literal`, `check_tier_imports`,
  `check_ac_tier_baseline`, `check_authority_reconcile` (declared vs detected at
  the enforceable ends). The impure edges that read the repo and fail CI.

## Published language

`__init__.__all__` (must equal `contract.interface`): the tier vocabulary +
matrix + the classifier's `band` / `classify_repo` / `BANDS`.
