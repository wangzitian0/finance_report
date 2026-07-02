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
event/outbox + middleware substrate — which declares no governed edges (it
imports only the unregistered ``src.database`` Base/session;
the config-bound ``api_rate_limiter`` instance is wired in ``src.main``) — is classed
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
    # No governed edges: this package imports only unregistered backend infra
    # (the shared ORM Base/session). The config-bound
    # ``api_rate_limiter`` instance is wired at the composition root (src.main),
    # so the substrate stays config-free.
    depends_on=[],
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
        # RateLimitConfig/RateLimitState data records are published (interface)
        # without separate unit declarations — like SubscriberRegistry. The
        # config-bound api_rate_limiter instance is built in src.main.
        Unit(
            name="RateLimiter",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/rate_limit.py",
        ),
    ],
    implementations={"be": "apps/backend/src/platform", "fe": None},
    interface=[
        "BaseAppException",
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
        "get_owned_or_404",
        "paginate",
        "raise_bad_request",
        "raise_conflict",
        "raise_gateway_timeout",
        "raise_internal_error",
        "raise_not_found",
        "raise_service_unavailable",
        "raise_too_large",
        "raise_too_many_requests",
        "raise_unauthorized",
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
        # ── EPIC-012 (foundation-libs) platform/api ACs homed here ──
        # Migrated from the EPIC-012 table: the leading "12" is dropped and the
        # group/seq preserved, so AC12.<g>.<s> becomes AC-platform.<g>.<s>
        # (numeric AC-<pkg>.<n>.<n> grammar). Only the moon/infra contract, the
        # BaseAppException hierarchy, and the API-surface platform ACs that have a
        # resolving Python anchor test are homed. LEFT in EPIC-012 (not homed):
        # the mechanical schema-move rows AC12.22.1/.2 (no anchor test), the
        # removed/deferred Prometheus-metrics rows AC12.24.1-.3 (no test), and the
        # frontend rows AC12.27.3 / AC12.28.3 (their `.test.ts` anchor is not a
        # Python path::func and this package is fe=None — same precedent as the
        # ledger cutover leaving EPIC-002's frontend rows in place). The package
        # tier (CODE-ONLY) gives proof_kind=exact.
        # ── group 19: Infrastructure — moon workspace contract (was AC12.19.*) ──
        ACRecord(
            id="AC-platform.19.1",
            statement=(
                "The moon workspace configuration files exist (the EPIC-001 "
                "moon/infra contract). Was EPIC-012 AC12.19.1."
            ),
            test=(
                "apps/backend/tests/infra/test_epic_001_contracts.py"
                "::test_epic_001_moon_workspace_configs_exist"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 21: Exceptions — BaseAppException hierarchy (was AC12.21.*) ──
        ACRecord(
            id="AC-platform.21.1",
            statement=(
                "BaseAppException stores the error_id attribute. "
                "Was EPIC-012 AC12.21.1."
            ),
            test=(
                "apps/backend/tests/infra/test_exceptions.py"
                "::test_base_app_exception_has_error_id"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.21.2",
            statement=(
                "BaseAppException stores the status_code attribute. "
                "Was EPIC-012 AC12.21.2."
            ),
            test=(
                "apps/backend/tests/infra/test_exceptions.py"
                "::test_base_app_exception_has_status_code"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.21.3",
            statement=(
                "BaseAppException is a subclass of Exception. Was EPIC-012 AC12.21.3."
            ),
            test=(
                "apps/backend/tests/infra/test_exceptions.py"
                "::test_base_app_exception_is_subclass_of_exception"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.21.4",
            statement=(
                "BaseAppException can be raised and caught with its fields intact. "
                "Was EPIC-012 AC12.21.4."
            ),
            test=(
                "apps/backend/tests/infra/test_exceptions.py"
                "::test_base_app_exception_raise_and_catch"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.21.5",
            statement=(
                "The BaseAppException handler serializes error_id and status_code "
                "into a structured JSON response. Was EPIC-012 AC12.21.5."
            ),
            test=(
                "apps/backend/tests/infra/test_exceptions.py"
                "::test_base_app_exception_handler_returns_structured_json"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 23: Rate limiting — global API middleware (was AC12.23.*) ──
        ACRecord(
            id="AC-platform.23.1",
            statement=(
                "The global rate-limit middleware exempts /health (never "
                "rate-limited). Was EPIC-012 AC12.23.1."
            ),
            test=(
                "apps/backend/tests/infra/test_rate_limit.py"
                "::test_global_rate_limit_middleware_exempts_health"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.23.2",
            statement=(
                "The global rate-limit middleware returns 429 with a Retry-After "
                "header after the limit is exceeded. Was EPIC-012 AC12.23.2."
            ),
            test=(
                "apps/backend/tests/infra/test_rate_limit.py"
                "::test_global_rate_limit_middleware_blocks_after_limit"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.23.3",
            statement=(
                "The global rate-limit middleware allows normal requests within "
                "the limit. Was EPIC-012 AC12.23.3."
            ),
            test=(
                "apps/backend/tests/infra/test_rate_limit.py"
                "::test_global_rate_limit_middleware_allows_normal_requests"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.23.4",
            statement=(
                "The global rate-limit middleware exempts /docs (never "
                "rate-limited). Was EPIC-012 AC12.23.4."
            ),
            test=(
                "apps/backend/tests/infra/test_rate_limit.py"
                "::test_global_rate_limit_middleware_exempts_docs"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 27: Structured API error contract (was AC12.27.*; .3 is FE) ──
        ACRecord(
            id="AC-platform.27.1",
            statement=(
                "An HTTPException-derived 404 returns a structured body with an "
                "error_id (plus detail + request_id). Was EPIC-012 AC12.27.1."
            ),
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC12_27_1_http_error_has_structured_error_id"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.27.2",
            statement=(
                "OpenAPI declares the shared ErrorResponse and references it for "
                "the common 4xx errors. Was EPIC-012 AC12.27.2."
            ),
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC12_27_2_openapi_declares_error_response_contract"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 28: Generated FE API types from OpenAPI (was AC12.28.*; .3 FE) ──
        ACRecord(
            id="AC-platform.28.1",
            statement=(
                "The generator emits the OpenAPI spec from the live FastAPI "
                "schema. Was EPIC-012 AC12.28.1."
            ),
            test=(
                "tests/tooling/test_generate_openapi_spec.py"
                "::test_AC12_28_1_generator_emits_types_from_openapi"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-platform.28.2",
            statement=(
                "The --check staleness gate fails when the committed OpenAPI spec "
                "drifts from the live schema. Was EPIC-012 AC12.28.2."
            ),
            test=(
                "tests/tooling/test_generate_openapi_spec.py"
                "::test_AC12_28_2_staleness_gate_detects_drift"
            ),
            priority="P2",
            status="done",
        ),
        # ── group 29: API-surface consistency sweep (was AC12.29.*) ──
        ACRecord(
            id="AC-platform.29.1",
            statement=(
                "Router status codes use status.HTTP_* constants (no raw-integer "
                "status_code literals); the async upload endpoint advertises 202. "
                "Was EPIC-012 AC12.29.1."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_1_status_codes_use_constants_and_async_uses_202"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.29.2",
            statement=(
                "The named unbounded list endpoints accept bounded limit/offset "
                "with an enforced le=MAX_PAGE_LIMIT. Was EPIC-012 AC12.29.2."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_2_named_unbounded_endpoints_are_bounded"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.29.3",
            statement=(
                "A single documented pagination convention is enforced "
                "(DEFAULT_PAGE_LIMIT/MAX_PAGE_LIMIT via PaginationParams); an "
                "over-max limit is rejected with 422. Was EPIC-012 AC12.29.3."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_3_pagination_convention_is_enforced"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.29.4",
            statement=(
                "No two API operations collide on (method, path); every router "
                "maps to exactly one OpenAPI tag. Was EPIC-012 AC12.29.4."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_4_no_route_or_tag_collisions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.29.5",
            statement=(
                "The deprecated POST /statements/{id}/approve and /reject are "
                "removed (404/405); the /review/* variants remain. "
                "Was EPIC-012 AC12.29.5."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_5_deprecated_statement_decision_endpoints_removed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.29.6",
            statement=(
                "Verb-in-path action URLs are renamed to resource-style nouns "
                "(/reconciliation/runs, /market-data/{fx,stocks}/syncs, "
                "/journal-entries/{id}/postings,/voidings). Was EPIC-012 AC12.29.6."
            ),
            test=(
                "apps/backend/tests/api/test_api_surface_consistency.py"
                "::test_AC12_29_6_verb_in_path_urls_renamed_to_resources"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
