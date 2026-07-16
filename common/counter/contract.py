"""The ``counter`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/counter``); every
``invariants[].test`` and ``roadmap[].test`` must resolve to a real test
function; ``depends_on`` must not introduce a forbidden upward/sideways edge.

The package's ACs live here in ``roadmap`` (the package-model AC registry). The
AC-registry generator (``common/meta/extension/generate_ac_registry.py``) sources them
directly from this contract, so they are NO LONGER mirrored into an EPIC table —
the contract is the single source.
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
    name="counter",
    status="active",
    # Deterministic tally + event emission, no LLM: a pure-code (CODE-ONLY) package.
    # Every AC in the roadmap inherits this tier.
    tier="CODE-ONLY",
    depends_on=["platform"],
    roles=["base", "extension"],
    units=[
        # base — pure value objects + the domain event type.
        Unit(name="CounterKey", kind=Kind.VALUE_OBJECT, module="base/types/key.py"),
        Unit(name="Count", kind=Kind.VALUE_OBJECT, module="base/types/count.py"),
        Unit(name="Incremented", kind=Kind.DOMAIN_EVENT, module="base/types/events.py"),
        # repository — the one split block: the abstract port lives in base/, the
        # SQL adapter in extension/ (dependency inversion, mechanism B).
        Unit(
            name="CounterRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/sql.py",
        ),
    ],
    implementations={"be": "apps/backend/src/counter", "fe": None},
    interface=[
        "Count",
        "CounterError",
        "CounterKey",
        "CounterRepository",
        "Incremented",
        "InvalidCounterKeyError",
        "NegativeCountError",
        "get_count",
        "increment",
        "read_count",
        "record_increment",
    ],
    events=["Incremented"],
    invariants=[
        Invariant(
            id="key-valid",
            statement=(
                "A CounterKey must be a non-empty lowercase dotted 'domain.action' "
                "identifier; an invalid key is unrepresentable (raises "
                "InvalidCounterKeyError at construction)."
            ),
            test="apps/backend/tests/counter/test_key.py::test_counter_key_rejects_invalid",
        ),
        Invariant(
            id="count-non-negative",
            statement=(
                "A Count is a non-negative tally; a negative value is "
                "unrepresentable (raises NegativeCountError at construction)."
            ),
            test="apps/backend/tests/counter/test_count.py::test_count_rejects_negative",
        ),
        # Structural guarantees live as invariants (no authority tier, not
        # matrix-constrained) — see common/meta/readme.md. The roadmap
        # below holds only the package's DOMAIN behavior, which inherits the
        # package tier.
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure core) + extension/ (edges).",
            test=(
                "tests/tooling/test_counter_package.py"
                "::test_AC_counter_1_1_counter_converges_by_layer"
            ),
        ),
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_counter_package.py"
                "::test_AC_counter_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement="The base/ layer never imports the package's own extension/ or the ORM.",
            test=(
                "tests/tooling/test_counter_package.py"
                "::test_AC_counter_1_2_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates counter with no violations.",
            test=(
                "tests/tooling/test_counter_package.py"
                "::test_AC_counter_1_4_package_contract_gate_passes_for_counter"
            ),
        ),
        Invariant(
            id="async-repository-composition",
            statement=(
                "CounterRepository is async, SqlCounterRepository structurally "
                "satisfies it, and extension/api delegates through base operations."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_counter_repository_5_async_adapter_and_api_composition"
            ),
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC-counter.1.1",
            statement=(
                "CounterKey validates the namespaced lowercase dotted "
                "'domain.action' shape and rejects invalid keys with "
                "InvalidCounterKeyError."
            ),
            test="apps/backend/tests/counter/test_key.py::test_counter_key_rejects_invalid",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-counter.1.2",
            statement=(
                "Count is a non-negative tally; constructing a negative count "
                "raises NegativeCountError."
            ),
            test="apps/backend/tests/counter/test_count.py::test_count_rejects_negative",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-counter.1.3",
            statement=(
                "increment bumps the per-(user, key) tally by one, returns the new "
                "per-user Count, and publishes an Incremented domain event through "
                "the platform EventBus."
            ),
            test="apps/backend/tests/counter/test_increment.py::test_increment_is_per_user",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-counter.1.4",
            statement=(
                "get_count returns the per-user count for a concrete user_id and "
                "the global count (sum across users) when user_id is None."
            ),
            test="apps/backend/tests/counter/test_query.py::test_global_vs_per_user_count",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-counter.repository.5",
            statement=(
                "The async CounterRepository port is structurally implemented by "
                "SqlCounterRepository and production API composition executes the "
                "same increment/get_count operations used by fakes."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_counter_repository_5_async_adapter_and_api_composition"
            ),
            priority="P0",
            status="done",
        ),
    ],
)
