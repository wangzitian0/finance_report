"""``PackageContract`` — the machine-checkable contract a package publishes.

A package = bounded context declares one :class:`PackageContract` instance in its
``contract.py``. The contract is the single source of truth for the package's
*published language* (``interface`` mirrors ``__init__.__all__``), its emitted
domain ``events``, the ``invariants`` it guarantees, and its ``roadmap`` (the
ACs it owns). ``tools/check_package_contract.py`` validates the live package
against this contract, so governance is *computed*, not hand-maintained.

stdlib + pydantic only by design: importable from the governance gate and from a
package's ``contract.py`` without pulling app/framework dependencies. The
authority-tier vocabulary and the tier->proof matrix come from the stdlib-only
:mod:`common.authority.authority_matrix` (the single machine source, also imported by
the lightweight SSOT tooling that must NOT pull pydantic).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

# Re-exported (hence noqa) so existing imports like
# `from common.governance.package_contract import TIER_VALID_PROOF_KINDS` keep
# resolving; the single source of these definitions is common.authority.authority_matrix.
from common.authority.authority_matrix import (  # noqa: F401
    AC_PROOF_KINDS,
    AC_TIERS,
    ACProofKind,
    ACTier,
    PackageTier,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
)

#: A package class. The three orthogonal kinds in the model:
#: - ``kernel``   — leaf value-language reused everywhere (e.g. ``money``);
#:                  depends on nothing in the app.
#: - ``platform`` — a reusable horizontal capability (e.g. ``counter``);
#:                  depends only on kernels.
#: - ``core``     — a vertical domain slice (e.g. ``ledger``);
#:                  may depend on platform + kernel packages.
PackageClass = Literal["core", "platform", "kernel"]

#: AC priority, mirroring the EPIC AC tables (P0 highest).
Priority = Literal["P0", "P1", "P2"]

#: AC lifecycle status within a package roadmap.
ACStatus = Literal["open", "done"]

#: Package lifecycle status. ``draft`` = still being designed (its authority
#: tier may be undecided); ``active`` = governed and shipped (tier MUST be
#: decided); ``deprecated`` = on the way out (still checked, but flagged).
PackageStatus = Literal["draft", "active", "deprecated"]

class Invariant(BaseModel):
    """A property the package guarantees, pinned to the test that proves it.

    ``test`` is a ``"path::func"`` reference (pytest node-id style, module path
    relative to the repo root) so the governance gate can resolve it to a real
    test function — an invariant with no executable proof is not an invariant.
    """

    id: str
    statement: str
    test: str


class ACRecord(BaseModel):
    """One acceptance criterion the package owns, in the package-model registry.

    The package roadmap is the *new* home for a package's ACs (the model where
    governance is computed from contracts). ``test`` is a ``"path::func"``
    reference, exactly like :class:`Invariant.test`, so each AC resolves to the
    test that anchors it.
    """

    id: str
    statement: str
    test: str
    priority: Priority
    status: ACStatus
    #: Proof kind the AC's test provides. The AC inherits its authority tier from
    #: the owning :class:`PackageContract` (tier is a module-design property, not a
    #: per-AC one), so ``proof_kind`` is the only tier-related attribute an AC
    #: carries. ``None`` resolves to the package tier's canonical kind
    #: (:data:`TIER_DEFAULT_PROOF_KIND`); an explicit value MUST be valid for the
    #: package tier per :data:`TIER_VALID_PROOF_KINDS` (e.g. under an LLM-LED/LLM-ONLY package
    #: an AC can never be ``exact``). Enforced by the owning ``PackageContract``.
    proof_kind: ACProofKind | None = None


class PackageContract(BaseModel):
    """The contract a package publishes — the unit the governance gate checks.

    Fields:
        name:            the package name (matches its ``common/<name>/`` dir).
        klass:           ``core`` / ``platform`` / ``kernel`` (the dependency tier).
        status:          ``draft`` / ``active`` / ``deprecated`` (package lifecycle).
        tier:            the package's permanent authority tier (:data:`PackageTier`);
                         ``None`` = undecided, allowed only while ``status="draft"``.
        depends_on:      names of packages this one may import (down-only edges).
        roles:           the role folders the implementation converges into
                         (e.g. ``["types", "ops", "store", "api"]``).
        implementations: where each implementation lives, by surface key
                         (``"be"`` / ``"fe"``); ``None`` means "no implementation
                         on that surface yet". The governance gate resolves
                         ``__all__`` against ``implementations["be"]``.
        interface:       the published language — must equal the BE
                         implementation's ``__init__.__all__``.
        events:          domain event type names this package publishes.
        invariants:      guaranteed properties, each pinned to a proving test.
        roadmap:         the ACs this package owns (the package-model AC registry).
    """

    name: str
    klass: PackageClass
    depends_on: list[str]
    interface: list[str]
    events: list[str]
    invariants: list[Invariant]
    roadmap: list[ACRecord]
    status: PackageStatus = "active"
    #: The package's permanent authority tier. ``None`` means "undecided" and is
    #: legal only for a ``draft`` package; an ``active``/``deprecated`` package
    #: must have resolved its tier to a concrete :data:`PackageTier`.
    tier: PackageTier | None = None
    roles: list[str] = []
    implementations: dict[str, str | None] = {}

    @model_validator(mode="after")
    def _tier_decided_and_proofs_match(self) -> PackageContract:
        """Enforce the module-design tier rules at construction.

        1. A shipped package has a decided tier: ``status != "draft"`` requires a
           concrete :data:`PackageTier` (a ``draft`` may stay ``tier=None`` — the
           "undecided" state that the legacy EPIC source spelled ``HU``).
        2. Every roadmap AC's proof kind is valid for the package's tier per the
           single matrix (:data:`TIER_VALID_PROOF_KINDS`); a missing kind resolves
           to the tier's canonical default and is materialized on the record. An
           undecided (``None``) tier skips the proof check — there is no tier to
           validate against yet.
        """
        if self.tier is None:
            if self.status != "draft":
                raise ValueError(
                    f"package {self.name!r}: status {self.status!r} requires a "
                    "decided authority tier (one of CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY); only a 'draft' "
                    "package may leave tier undecided (the legacy 'HU' state)."
                )
            return self

        valid = TIER_VALID_PROOF_KINDS[self.tier]
        for ac in self.roadmap:
            kind = ac.proof_kind or TIER_DEFAULT_PROOF_KIND[self.tier]
            if kind not in valid:
                raise ValueError(
                    f"package {self.name!r} AC {ac.id}: proof_kind {kind!r} is "
                    f"not valid for the package tier {self.tier} "
                    f"(valid: {sorted(valid)}). Under an LLM-LED/LLM-ONLY package an AC can "
                    "never be proven by an exact golden assertion."
                )
            ac.proof_kind = kind
        return self
