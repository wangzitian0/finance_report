"""The ``counter`` package's machine-checkable :class:`PackageContract`.

This is the single source of truth the governance gate
(``tools/check_package_contract.py``) validates the live package against:
``interface`` must equal ``counter.__all__``; every ``invariants[].test`` and
``roadmap[].test`` must resolve to a real test function; ``depends_on`` must not
introduce a forbidden upward/sideways edge.

The package's ACs live here in ``roadmap`` (the package-model AC registry); they
are mirrored into ``docs/project/EPIC-025`` so the existing AC index gate stays
green while the package model is the worked example.
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
    depends_on=[],
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
            id="AC25.6.1",
            statement=(
                "CounterKey validates the namespaced 'domain.action' shape and "
                "rejects invalid keys with InvalidCounterKeyError."
            ),
            test="apps/backend/tests/counter/test_key.py::test_counter_key_rejects_invalid",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC25.6.2",
            statement=("Count is non-negative; constructing a negative count raises NegativeCountError."),
            test="apps/backend/tests/counter/test_count.py::test_count_rejects_negative",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC25.6.3",
            statement=(
                "increment bumps the per-(user, key) tally by one, returns the new "
                "per-user Count, and emits an Incremented domain event."
            ),
            test="apps/backend/tests/counter/test_increment.py::test_increment_is_per_user",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC25.6.4",
            statement=(
                "get_count returns the per-user count for a concrete user_id and the "
                "global count (sum across users) when user_id is None."
            ),
            test="apps/backend/tests/counter/test_query.py::test_global_vs_per_user_count",
            priority="P1",
            status="done",
        ),
    ],
)
