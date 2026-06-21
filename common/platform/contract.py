"""The ``platform`` package's machine-checkable :class:`PackageContract`.

``platform`` is the meta layer's first *runtime* capability: a domain
**EventBus implemented via the transactional outbox pattern**. The governance
gate (``tools/check_package_contract.py``) validates the BE implementation
(``apps/backend/src/platform``) against this contract: ``interface`` must equal
the implementation's ``__all__``; every ``invariants[].test`` /
``roadmap[].test`` must resolve to a real test; and ``depends_on`` must introduce
no forbidden import edge.

### Why ``klass="kernel"``

The ``klass`` is a position in the import DAG, not a marketing label. The gate
ranks ``kernel(0) < platform(1) < core(2)`` and forbids any package importing a
target of **equal or higher** rank. ``counter`` (a ``platform`` package) must
import this package's :class:`DomainEvent` (its ``Incremented`` is a
``DomainEvent``) and write through its bus — a strictly *downward* edge only if
``platform`` (the package) ranks **below** ``counter``. So this foundational
event/outbox substrate — which itself imports nothing registered (only the
unregistered ``src.database`` Base/session) — is classed ``kernel``: a leaf the
whole app builds events on. "Meta layer" describes its *role* (the first runtime
capability of the platform substrate); ``kernel`` is its honest DAG rank.
"""

from __future__ import annotations

from common.governance.package_contract import (
    ACRecord,
    Invariant,
    PackageContract,
)

CONTRACT = PackageContract(
    name="platform",
    klass="kernel",
    status="active",
    depends_on=[],
    roles=["events", "store"],
    implementations={"be": "apps/backend/src/platform", "fe": None},
    interface=[
        "DomainEvent",
        "EventBus",
        "Outbox",
        "OutboxEventBus",
        "OutboxRelay",
        "OutboxRepository",
        "RecordingEventBus",
        "SubscriberRegistry",
    ],
    events=[],
    invariants=[
        Invariant(
            id="outbox-write-is-atomic",
            statement=(
                "Publishing through the OutboxEventBus writes the event in the "
                "caller's transaction: rollback leaves no outbox row, commit "
                "leaves exactly the published rows (atomic with the domain write)."
            ),
            test=(
                "apps/backend/tests/platform/test_outbox_atomicity.py"
                "::test_rollback_leaves_no_outbox_row"
            ),
        ),
        Invariant(
            id="relay-dispatches-once-post-commit",
            statement=(
                "The relay reads committed pending rows in id order, dispatches "
                "each to subscribed handlers, marks it published, and a second "
                "run_once does not re-dispatch a published row."
            ),
            test=(
                "apps/backend/tests/platform/test_relay.py"
                "::test_second_run_does_not_redispatch_published"
            ),
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC25.7.1",
            statement=(
                "The OutboxEventBus writes a domain event into the shared outbox "
                "table using the caller's AsyncSession; a rolled-back transaction "
                "leaves no row and a committed one leaves exactly the published "
                "rows (transactional-outbox atomicity)."
            ),
            test=(
                "apps/backend/tests/platform/test_outbox_atomicity.py"
                "::test_commit_leaves_exactly_one_outbox_row"
            ),
            priority="P0",
            status="done",
            tier="PC",
        ),
        ACRecord(
            id="AC25.7.2",
            statement=(
                "OutboxRelay.run_once reads committed pending rows in enqueue "
                "order, dispatches each to its subscribed handlers with the "
                "rehydrated DomainEvent, and marks the rows published."
            ),
            test=(
                "apps/backend/tests/platform/test_relay.py"
                "::test_run_once_dispatches_and_marks_published"
            ),
            priority="P0",
            status="done",
            tier="PC",
        ),
        ACRecord(
            id="AC25.7.3",
            statement=(
                "Dispatch is at-least-once: a second run_once does not re-deliver "
                "published rows, and re-delivery of a still-pending row is safe "
                "for an idempotent handler."
            ),
            test=(
                "apps/backend/tests/platform/test_relay.py"
                "::test_redelivery_of_pending_is_idempotent_safe"
            ),
            priority="P1",
            status="done",
            tier="PC",
        ),
        ACRecord(
            id="AC25.7.4",
            statement=(
                "The platform package converges by role and its published "
                "language equals contract.interface; check_package_contract "
                "validates platform with no violations."
            ),
            test=(
                "apps/backend/tests/platform/test_contract.py"
                "::test_platform_package_passes_governance_gate"
            ),
            priority="P1",
            status="done",
            tier="PC",
        ),
        ACRecord(
            id="AC25.7.5",
            statement=(
                "counter.record_increment bumps the per-(user, key) tally and "
                "enqueues a counter.Incremented event into the shared outbox in "
                "the SAME transaction (rollback leaves neither tally nor event)."
            ),
            test=(
                "apps/backend/tests/counter/test_outbox_emit.py"
                "::test_record_increment_writes_incremented_atomically"
            ),
            priority="P1",
            status="done",
            tier="PC",
        ),
    ],
)
