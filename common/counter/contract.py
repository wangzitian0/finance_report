"""The ``counter`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/counter``); every
``invariants[].test`` and ``roadmap[].test`` must resolve to a real test
function; ``depends_on`` must not introduce a forbidden upward/sideways edge.

The package's ACs live here in ``roadmap`` (the package-model AC registry). The
AC-registry generator (``common/ssot/generate_ac_registry.py``) sources them
directly from this contract, so they are NO LONGER mirrored into an EPIC table —
the contract is the single source.
"""

from __future__ import annotations

from common.governance.package_contract import (
    ACRecord,
    Invariant,
    PackageContract,
)

CONTRACT = PackageContract(
    name="counter",
    klass="platform",
    status="active",
    # Deterministic tally + event emission, no LLM: a pure-code (PC) package.
    # Every AC in the roadmap inherits this tier.
    tier="PC",
    depends_on=["platform"],
    roles=["types", "ops", "store", "api"],
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
    ],
    roadmap=[
        ACRecord(
            id="AC-counter.1.1",
            statement=(
                "CounterKey validates the namespaced lowercase dotted "
                "'domain.action' shape and rejects invalid keys with "
                "InvalidCounterKeyError; the package converges by role and "
                "contract.interface equals __init__.__all__."
            ),
            test="apps/backend/tests/counter/test_key.py::test_counter_key_rejects_invalid",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-counter.1.2",
            statement=(
                "Count is a non-negative tally; constructing a negative count "
                "raises NegativeCountError; domain types never import the "
                "store/api/ORM."
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
                "the platform EventBus; ops depend only on the CounterRepository "
                "port and the EventBus port, never the ORM."
            ),
            test="apps/backend/tests/counter/test_increment.py::test_increment_is_per_user",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-counter.1.4",
            statement=(
                "get_count returns the per-user count for a concrete user_id and "
                "the global count (sum across users) when user_id is None; "
                "check_package_contract validates counter against its "
                "PackageContract."
            ),
            test="apps/backend/tests/counter/test_query.py::test_global_vs_per_user_count",
            priority="P1",
            status="done",
        ),
    ],
)
