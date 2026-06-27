"""The ``platform`` package's machine-checkable :class:`PackageContract`.

``platform`` is the meta layer's *runtime middleware* substrate. Its first
capability is a domain **EventBus implemented via the transactional outbox
pattern**; it also hosts the cross-cutting request **rate limiter** (a
process-global throttle that is request middleware too). It is the technical
substrate logically labelled *middleware* (issue #1427); the package keeps the
name ``platform`` (the existing contract + ACs use it) and treats *middleware* as
the umbrella label. The governance gate
(``tools/check_package_contract.py``) validates the BE implementation
(``apps/backend/src/platform``) against this contract: ``interface`` must equal
the implementation's ``__all__``; every ``invariants[].test`` /
``roadmap[].test`` must resolve to a real test; ``depends_on`` must introduce
no forbidden import edge; and each declared ``unit`` sits in the layer its
``kind`` dictates (``base``/``extension``), with the bus + outbox repository
each split into a base **port** + an extension **adapter**.

### The building-block layering (``units``)

The package converges into ``base`` (pure core) + ``extension`` (impure edges),
mirroring ``counter``. The headline is the **port/adapter split** (mechanism B,
dependency inversion): the ``EventBus`` and ``OutboxRepository`` ports live in
``base`` so the pure core and consumer packages depend only on abstractions,
while their concrete adapters (``OutboxEventBus``/``RecordingEventBus`` and the
SQL ``Outbox`` adapter) live in ``extension``. Because the gate's ``KIND_LAYER``
has no separate "event-bus split" kind, the two ports are modelled with
``kind=REPOSITORY`` (the one base-port/extension-adapter split the gate
recognises); the concrete bus adapters + relay are ``kind=EVENT_BUS`` (extension).
``DomainEvent`` is a base ``domain-event`` record; ``Outbox`` is the entity whose
ORM model lives with the SQL adapter in ``extension`` (declared taxonomy-only, no
placed module, exactly as ``counter`` keeps its ``CounterTally`` table in
``extension``).

### Why ``klass="kernel"``

The ``klass`` is a position in the import DAG, not a marketing label. The gate
ranks ``kernel(0) < platform(1) < core(2)`` and forbids any package importing a
target of **equal or higher** rank. ``counter`` (a ``platform`` package) must
import this package's :class:`DomainEvent` (its ``Incremented`` is a
``DomainEvent``) and write through its bus — a strictly *downward* edge only if
``platform`` (the package) ranks **below** ``counter``. So this foundational
event/outbox + middleware substrate — whose only registered edge is the
same-class ``kernel`` -> ``kernel`` ``depends_on=["config"]`` (the rate limiter
reads the config singleton via its bare published root; otherwise it imports only
the unregistered ``src.database`` Base/session and ``src.logger``) — is classed
``kernel``: a leaf the whole app builds events on. "Meta layer" describes its
*role* (the runtime middleware capabilities of the platform substrate);
``kernel`` is its honest DAG rank.
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
    name="platform",
    klass="kernel",
    status="active",
    # Deterministic event/outbox substrate, no LLM: a pure-code (CODE-ONLY) package.
    # Every AC in the roadmap inherits this tier.
    tier="CODE-ONLY",
    # The request rate-limiter middleware reads the backend config singleton via
    # its bare published root (``import src.config``), the one registered-package
    # edge this package declares (a same-class kernel -> kernel edge, acyclic;
    # config has depends_on=[]). All other imports it makes (src.logger, the shared
    # ORM Base/session) are unregistered backend infra, not governed edges.
    depends_on=["config"],
    roles=["base", "extension"],
    units=[
        # base — the domain-event record (the textbook mechanism-C type).
        Unit(name="DomainEvent", kind=Kind.DOMAIN_EVENT, module="base/event.py"),
        # the two split blocks (mechanism B): each port lives in base/, its
        # concrete adapter in extension/. The event bus has no dedicated "split"
        # kind in KIND_LAYER, so its port/adapter inversion is modelled the same
        # way a repository is — a base port + an extension adapter.
        Unit(
            name="EventBus",
            kind=Kind.REPOSITORY,
            module="base/bus.py",
            impl="extension/bus.py",
        ),
        Unit(
            name="OutboxRepository",
            kind=Kind.REPOSITORY,
            module="base/outbox.py",
            impl="extension/sql.py",
        ),
        # entity — the shared outbox row. Its ORM model lives with the SQL adapter
        # in extension/ (like counter's CounterTally), so it is declared
        # taxonomy-only (no placed module) to keep base/ free of the ORM.
        Unit(name="Outbox", kind=Kind.ENTITY),
        # extension — the concrete event-bus adapters + the post-commit relay.
        Unit(name="OutboxEventBus", kind=Kind.EVENT_BUS, module="extension/bus.py"),
        Unit(name="RecordingEventBus", kind=Kind.EVENT_BUS, module="extension/bus.py"),
        Unit(name="OutboxRelay", kind=Kind.EVENT_BUS, module="extension/relay.py"),
        # extension — the cross-cutting request rate-limiter. It is an impure,
        # process-global middleware service (throttles inbound requests per key),
        # so it is a domain-service, which KIND_LAYER places in extension/. Its
        # RateLimitConfig/RateLimitState data records and the app-wide
        # api_rate_limiter instance live with it in the same module and are
        # published (interface) without separate unit declarations — exactly as
        # SubscriberRegistry is published without a unit.
        Unit(
            name="RateLimiter",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/rate_limit.py",
        ),
    ],
    implementations={"be": "apps/backend/src/platform", "fe": None},
    interface=[
        "DomainEvent",
        "EventBus",
        "Outbox",
        "OutboxEventBus",
        "OutboxRelay",
        "OutboxRepository",
        "RateLimitConfig",
        "RateLimitState",
        "RateLimiter",
        "RecordingEventBus",
        "SubscriberRegistry",
        "api_rate_limiter",
    ],
    events=[],
    invariants=[
        # Structural guarantees (no authority tier, not matrix-constrained) — the
        # building-block layering this cutover establishes. See counter's contract
        # for the precedent.
        Invariant(
            id="converges-by-layer",
            statement="The package converges into base/ (pure core) + extension/ (edges).",
            test=(
                "tests/tooling/test_platform_package.py"
                "::test_platform_converges_by_layer"
            ),
        ),
        Invariant(
            id="repository-split",
            statement=(
                "The event-bus and outbox-repository ports each split into a base "
                "port + an extension adapter (dependency inversion, mechanism B)."
            ),
            test=(
                "tests/tooling/test_platform_package.py::test_platform_repository_split"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement="The base/ layer never imports the package's own extension/ or the ORM.",
            test=(
                "tests/tooling/test_platform_package.py"
                "::test_platform_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_platform_package.py"
                "::test_platform_interface_equals_published_language"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates platform with no violations.",
            test=(
                "tests/tooling/test_platform_package.py"
                "::test_platform_package_contract_gate_passes"
            ),
        ),
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
            id="AC-platform.1.1",
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
        ),
        ACRecord(
            id="AC-platform.1.2",
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
        ),
        ACRecord(
            id="AC-platform.1.3",
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
        ),
        ACRecord(
            id="AC-platform.1.4",
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
        ),
        ACRecord(
            id="AC-platform.1.5",
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
        ),
    ],
)
