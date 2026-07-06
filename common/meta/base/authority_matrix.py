"""Single machine source of the authority-tier vocabulary + tier->proof matrix.

This is the canonical machine mirror of ``common/meta/readme.md``. It is
**stdlib-only by design** (``typing`` only): importable by the lightweight SSOT
tooling — the registry generator (``generate_ac_registry``), the proof-kind gate
(``check_ac_proof_kind``), and the CODE/LLM classifier (``authority_classifier``)
— WITHOUT pulling ``pydantic``, so the CI lint env (``uv run --with pyyaml …``)
keeps working. ``common.meta``'s pydantic ``PackageContract`` model re-uses
these same definitions for its construction-time validation.

**One vocabulary, two views.** The four tier names are a single ordered
CODE↔LLM spectrum. They are used by BOTH:

- the **declared** view — ``PackageContract.tier`` (a package's authorial intent);
- the **detected** view — the per-package band the ``authority_classifier``
  measures from test shapes (``PACKAGE_TIERS`` IS the band scale).

So ``authority_classifier`` imports :data:`PACKAGE_TIERS` from here instead of
re-declaring band names — there is exactly one vocabulary and it cannot drift.
(Renamed from the legacy PC/CP/LP/PL on 2026-06-24: PC→CODE-ONLY, CP→CODE-LED,
LP→LLM-LED, PL→LLM-ONLY.)
"""

from __future__ import annotations

from typing import Literal, get_args

#: The four permanent module-design authority tiers, ordered by how much of the
#: output the LLM produces (0 → full). This IS the classifier's band scale.
PackageTier = Literal["CODE-ONLY", "CODE-LED", "LLM-LED", "LLM-ONLY"]

#: Legacy per-AC tier vocabulary used by the EPIC-table ``{tier:XX}`` marker
#: source; adds ``HU`` (= "undecided") for pre-package ACs not yet classified
#: (in the package model "undecided" is a ``draft`` package with ``tier=None``).
ACTier = Literal["CODE-ONLY", "CODE-LED", "LLM-LED", "LLM-ONLY", "HU"]

#: Proof kind an AC's test provides.
ACProofKind = Literal["property", "invariant", "eval", "exact", "evidence", "smoke"]

#: tier -> the proof kinds the matrix accepts for that tier.
TIER_VALID_PROOF_KINDS: dict[str, frozenset[str]] = {
    "CODE-ONLY": frozenset({"exact", "property"}),
    "CODE-LED": frozenset({"exact", "property"}),
    "HU": frozenset({"evidence"}),
    "LLM-LED": frozenset({"property", "invariant", "eval"}),
    "LLM-ONLY": frozenset({"eval", "smoke"}),
}

#: tier -> canonical proof kind when an AC declares no explicit ``proof_kind``.
#: Each default is a member of that tier's :data:`TIER_VALID_PROOF_KINDS`.
TIER_DEFAULT_PROOF_KIND: dict[str, str] = {
    "CODE-ONLY": "exact",
    "CODE-LED": "exact",
    "HU": "evidence",
    "LLM-LED": "property",
    "LLM-ONLY": "smoke",
}

#: Canonical vocabularies as tuples, derived from the Literals so the tuple form
#: (used by the ssot tooling) cannot drift from the type form.
AC_TIERS: tuple[str, ...] = get_args(ACTier)
AC_PROOF_KINDS: tuple[str, ...] = get_args(ACProofKind)

#: The four permanent package tiers as a tuple (no HU — that is the draft state),
#: ORDERED by LLM-share so it doubles as the classifier's band scale.
PACKAGE_TIERS: tuple[str, ...] = get_args(PackageTier)
