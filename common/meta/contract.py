"""The ``meta`` package's own :class:`PackageContract`.

The package model self-hosts: the meta package that *defines* what a package is
(``PackageContract`` / ``ACRecord`` / ``Invariant`` / ``Unit`` / ``Kind`` and the
``check_package_contract`` gate) is itself a package, with a ``readme.md`` (the
package-model spec), this ``contract.py``, and a ``todo.md``. It is discovered
and validated by the very gate it ships, so the model proves itself.

meta is also the Layout-3 exemplar: it converges into the ``base`` / ``extension``
/ ``data`` layers it governs, and declares its DDD building-block ``units`` (the
``PackageContract`` aggregate root + its value objects in ``base``, the gate as a
``domain-service`` in ``extension``, and ``contract_index`` as a ``projection`` in
``data``). Its BE implementation is ``common/meta`` (the same directory): the
published language is ``common/meta/__init__.py``'s ``__all__``.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="meta",
    klass="platform",
    status="active",
    # The package-model gate is deterministic code (AST + set comparison), no
    # LLM: a pure-code (CODE-ONLY) package. It also OWNS the authority-tier rules below.
    tier="CODE-ONLY",
    depends_on=["authority"],
    roles=["base", "extension", "data"],
    units=[
        # base — the pure model: the PackageContract aggregate root + its value
        # objects, and the building-block taxonomy. All live in base/package_contract.py.
        Unit(
            name="PackageContract",
            kind=Kind.AGGREGATE_ROOT,
            module="base/package_contract.py",
        ),
        Unit(
            name="ACRecord", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"
        ),
        Unit(
            name="Invariant", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"
        ),
        Unit(name="Unit", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"),
        Unit(name="Kind", kind=Kind.VALUE_OBJECT, module="base/package_contract.py"),
        # extension — the impure edge: the governance gate (a domain service that
        # walks the tree and validates every package against its contract).
        Unit(
            name="check_package_contract",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/check_package_contract.py",
        ),
        # data — the read-model: the computed meta-index over all contracts.
        Unit(name="contract_index", kind=Kind.PROJECTION, module="data/projection.py"),
    ],
    implementations={"be": "common/meta", "fe": None},
    interface=[
        "ACRecord",
        "Invariant",
        "Kind",
        "PackageContract",
        "Unit",
        "contract_index",
    ],
    events=[],
    invariants=[
        Invariant(
            id="contract-equals-published-language",
            statement=(
                "A package's contract.interface must equal its BE implementation's "
                "__init__.__all__; a drift between the declared and published "
                "language is reported by the gate."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_interface_mismatch_is_reported"
            ),
        ),
        Invariant(
            id="unproven-reference-is-rejected",
            statement=(
                "Every invariants[].test and roadmap[].test must resolve to a real "
                "test function; an unresolved reference is a gate failure."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_unresolved_invariant_and_roadmap_refs_are_reported"
            ),
        ),
        Invariant(
            id="dag-down-only",
            statement=(
                "A package's implementation may import only strictly-lower-class "
                "packages declared in depends_on; an upward/sideways/undeclared "
                "edge is rejected (the project stays a DAG)."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_upward_edge_is_forbidden"
            ),
        ),
        Invariant(
            id="active-package-has-a-decided-tier",
            statement=(
                "Authority tier is a module-design property declared once on the "
                "PackageContract (docs/ssot/authority-tiers.md). An active/"
                "deprecated package must have resolved its tier to one of "
                "CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY; only a draft package may leave tier undecided (the "
                "legacy 'HU' state), so a shipped untyped package is "
                "unrepresentable."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_active_package_must_declare_a_tier"
            ),
        ),
        Invariant(
            id="ac-proof-kind-satisfies-package-tier-matrix",
            statement=(
                "Every roadmap AC's proof_kind must be valid for the package's "
                "tier per the single machine matrix "
                "(package_contract.TIER_VALID_PROOF_KINDS); PackageContract "
                "enforces it at construction, so a contract that violates the "
                "tier->proof matrix (e.g. an LLM-LED/LLM-ONLY package with an AC claiming an "
                "exact golden proof) fails to import."
            ),
            test=(
                "tests/tooling/test_check_package_contract.py"
                "::test_package_proof_kind_must_satisfy_the_tier_matrix"
            ),
        ),
        # Structural guarantees about meta ITSELF as the Layout-3 exemplar (no
        # authority tier, not matrix-constrained — see docs/ssot/authority-tiers.md).
        Invariant(
            id="meta-converges-by-layer",
            statement=(
                "The meta package converges into base/ (the pure model) + "
                "extension/ (the gate) + data/ (the projection) — the layout it "
                "governs."
            ),
            test=("tests/tooling/test_meta_layering.py::test_meta_converges_by_layer"),
        ),
        Invariant(
            id="meta-base-is-pure",
            statement=(
                "The meta base/ layer never imports its own extension/ or data/ — "
                "the model is the pure, downward-only core."
            ),
            test="tests/tooling/test_meta_layering.py::test_meta_base_is_pure",
        ),
    ],
    roadmap=[
        # The governance gate's building-block behavior — meta's domain. Each AC
        # is proven by a negative test driving the gate against a synthetic
        # package that violates the rule.
        ACRecord(
            id="AC-meta.kind.1",
            statement=(
                "A declared unit must live in the layer its kind dictates "
                "(KIND_LAYER); a unit whose module sits in the wrong layer is "
                "rejected (mechanism A)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_1_unit_misplacement_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.2",
            statement=(
                "A repository unit must split into a base port + an extension "
                "adapter; a port outside base/ or an adapter outside extension/ is "
                "rejected (mechanism B, dependency inversion)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_2_repository_requires_port_and_adapter"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.3",
            statement=(
                "The data/ layer is a sink: nothing in base/ or extension/ may "
                "import the package's own data/, so the read-model never feeds back "
                "into the write side."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_3_data_layer_is_a_sink"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.projection.1",
            statement=(
                "contract_index is a pure projection over the contracts it is "
                "handed: registry, AC index, reverse-dependency consumers, and "
                "per-package units-by-layer, with no I/O of its own."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_projection_1_contract_index_is_pure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-meta.kind.4",
            statement=(
                "A value-type package may declare value-object units for the "
                "taxonomy without the physical base/extension split; the gate "
                "accepts it (additive) and still passes."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_kind_4_value_type_packages_pass"
            ),
            priority="P2",
            status="done",
        ),
        # One-transaction-per-domain (issue #1460, Decision B made executable):
        # one DB transaction belongs to exactly one domain; cross-domain changes
        # go through a published interface or an id + a domain event — never a
        # shared cross-domain transaction or a cross-domain FK. AC-meta.event.1
        # (outbox atomicity) is a runtime property left to the platform package's
        # own tests, not this structural gate, so it is intentionally not listed.
        ACRecord(
            id="AC-meta.txn.1",
            statement=(
                "A base unit reaching into another registered domain's unpublished "
                "object (an internal entity/aggregate, not a symbol in that "
                "package's __all__) is rejected; a cross-domain reference goes "
                "through the published interface (root import or a published "
                "symbol) or by id."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_1_base_deep_import_of_other_domain_object_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.txn.2",
            statement=(
                "A domain's extension reaching into another domain's ORM/models (an "
                "unpublished internal) is rejected: a cross-domain effect must be a "
                "published domain event, not another domain's tables written in the "
                "same transaction. A plain deep 'import src.<other>.<sub>' is "
                "rejected too (it names no published symbol)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_2_extension_writing_other_domain_orm_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-meta.txn.3",
            statement=(
                "A SQLAlchemy ForeignKey/relationship whose target table or model "
                "belongs to another registered domain is rejected; a cross-domain "
                "reference must be an id column resolved via the interface/event, "
                "not a database FK. Detection is AST-only/best-effort on the "
                "string-target forms (documented in the gate)."
            ),
            test=(
                "tests/tooling/test_meta_layering.py"
                "::test_AC_meta_txn_3_cross_domain_fk_is_rejected"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
