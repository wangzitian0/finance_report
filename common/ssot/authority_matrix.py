"""Single machine source of the authority-tier vocabulary + tier->proof matrix.

This is the canonical machine mirror of ``docs/ssot/authority-tiers.md``. It is
**stdlib-only by design** (``typing`` only): importable by the lightweight SSOT
tooling — the registry generator (``generate_ac_registry``) and the proof-kind
gate (``check_ac_proof_kind``) — WITHOUT pulling ``pydantic``, so the CI lint
env (``uv run --with pyyaml …``) keeps working. ``common.governance``'s
pydantic ``PackageContract`` model re-uses these same definitions for its
construction-time validation, so there is exactly one matrix and it cannot drift
between the model and the gates.
"""

from __future__ import annotations

from typing import Literal, get_args

#: The four permanent module-design authority tiers (SSOT: authority-tiers.md).
PackageTier = Literal["PC", "CP", "LP", "PL"]

#: Legacy per-AC tier vocabulary used only by the EPIC-table ``{tier:XX}`` marker
#: source; still recognizes ``HU`` for the handful of pre-package ACs that carry
#: it (in the package model "undecided" is a ``draft`` package with ``tier=None``).
ACTier = Literal["PC", "CP", "HU", "LP", "PL"]

#: Proof kind an AC's test provides.
ACProofKind = Literal["property", "invariant", "eval", "exact", "evidence", "smoke"]

#: tier -> the proof kinds the matrix accepts for that tier.
TIER_VALID_PROOF_KINDS: dict[str, frozenset[str]] = {
    "PC": frozenset({"exact", "property"}),
    "CP": frozenset({"exact", "property"}),
    "HU": frozenset({"evidence"}),
    "LP": frozenset({"property", "invariant", "eval"}),
    "PL": frozenset({"eval", "smoke"}),
}

#: tier -> canonical proof kind when an AC declares no explicit ``proof_kind``.
#: Each default is a member of that tier's :data:`TIER_VALID_PROOF_KINDS`.
TIER_DEFAULT_PROOF_KIND: dict[str, str] = {
    "PC": "exact",
    "CP": "exact",
    "HU": "evidence",
    "LP": "property",
    "PL": "smoke",
}

#: Canonical vocabularies as tuples, derived from the Literals so the tuple form
#: (used by the ssot tooling) cannot drift from the type form.
AC_TIERS: tuple[str, ...] = get_args(ACTier)
AC_PROOF_KINDS: tuple[str, ...] = get_args(ACProofKind)
