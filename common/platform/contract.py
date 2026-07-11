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

### Why layer ``infra``

The layer is a position in the import DAG, not a marketing label. The gate
ranks ``meta(L0) < infra(L1) < middleware(L2) < domain(L3) < app(L4)`` and
forbids any package importing a
target of **equal or higher** rank. ``counter`` (a ``middleware`` package, L2) must
import this package's :class:`DomainEvent` (its ``Incremented`` is a
``DomainEvent``) and write through its bus — a strictly *downward* edge only if
``platform`` (the package) ranks **below** ``counter``. So this foundational
event/outbox + middleware substrate — which declares no governed edges (it
imports only the unregistered ``src.database`` Base/session;
the config-bound ``api_rate_limiter`` instance is wired in ``src.main``) — is placed
in ``infra`` (L1): a leaf the whole app builds events on. "Meta layer" describes its
*role* (the runtime middleware capabilities of the platform substrate);
``infra`` is its honest DAG rank.
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
        "AppConfig",
        "BASE_CURRENCY_KEY",
        "BaseAppException",
        "DomainEvent",
        "EventBus",
        "Outbox",
        "OutboxEventBus",
        "OutboxRelay",
        "OutboxRepository",
        "PingState",
        "RateLimitConfig",
        "RateLimitState",
        "RateLimiter",
        "RecordingEventBus",
        "SubscriberRegistry",
        "WorkflowEvent",
        "WorkflowEventFamily",
        "WorkflowEventSeverity",
        "WorkflowEventStatus",
        "WorkflowReportImpact",
        "WorkflowSession",
        "WorkflowSessionStatus",
        "get_owned_or_404",
        "get_workflow_status",
        "list_workflow_events_response",
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
        "register_readiness_provider",
        "register_uploaded_document_readers",
        "update_workflow_event_status",
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
                "The platform package converges into the base/extension layering and its published "
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
        # ── group 30: workflow-event-model — the product-level event
        # contract (was EPIC-019 AC19.1, migration closeout continuation,
        # #1663 / #1712) ──
        ACRecord(
            id="AC-platform.30.1",
            statement=(
                "The workflow-event SSOT registers event families, "
                "severity/actionability, lifecycle states, dedupe rules, "
                "internal action links, indexes, and the relationship to "
                "audit logs. Was EPIC-019 AC19.1.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_1_1_workflow_event_ssot_registers_manifest_owner"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.30.2",
            statement=(
                "The backend model defines a user-scoped workflow_events "
                "read model with explicit enum names, lifecycle status, "
                "UNIQUE(user_id, dedupe_key), and badge/inbox read indexes. "
                "Was EPIC-019 AC19.1.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_1_2_workflow_event_model_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.30.3",
            statement=(
                "Pydantic schemas validate the workflow event contract and "
                "reject external action_href values. Was EPIC-019 AC19.1.3."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_1_3_workflow_event_schema_rejects_external_action_href"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.30.4",
            statement=(
                "The workflow event service deterministically upserts a "
                "derived event from existing statement/upload state without "
                "duplicating on rerun. Was EPIC-019 AC19.1.4."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.30.5",
            statement=(
                "Workflow event reads and lifecycle changes are user "
                "isolated. Was EPIC-019 AC19.1.5."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_1_5_workflow_event_lifecycle_is_user_isolated"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 31: workflow-status-api — GET /workflow/status,
        # GET /workflow/events, PATCH /workflow/events/{id} (was EPIC-019
        # AC19.2, migration closeout continuation, #1663 / #1712) ──
        ACRecord(
            id="AC-platform.31.1",
            statement=(
                "Workflow status schemas define stable primary state, next "
                "action, report readiness, and event count response "
                "contracts for later UI consumers. Was EPIC-019 AC19.2.1."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_1_workflow_status_schema_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.2",
            statement=(
                "GET /workflow/status returns user-scoped empty, "
                "processing, needs-action, blocked, and ready summaries "
                "with deterministic priority rules. Was EPIC-019 AC19.2.2."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.3",
            statement=(
                "GET /workflow/events returns bounded, user-scoped, "
                "deduplicated events, excludes archived events by default, "
                "and supports status filtering. Was EPIC-019 AC19.2.3."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.4",
            statement=(
                "PATCH /workflow/events/{id} updates only the authenticated "
                "user's event lifecycle and returns 404 for missing or "
                "non-owned events. Was EPIC-019 AC19.2.4."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_4_workflow_event_patch_is_user_scoped"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.5",
            statement=(
                "Status and events reads run a deterministic derived sync "
                "without duplicating events or resetting read/archive "
                "lifecycle state. Was EPIC-019 AC19.2.5."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_5_workflow_reads_sync_derived_events_without_lifecycle_reset"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.6",
            statement=(
                "The workflow API router is mounted and documented in the "
                "workflow-events SSOT as the compact read path for later UI "
                "slices. Was EPIC-019 AC19.2.6."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_2_6_workflow_router_and_ssot_document_compact_read_path"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.31.7",
            statement=(
                "GET /workflow/events session summaries reuse the "
                "authoritative get_workflow_status derivation, so a "
                "blocked active session never reports primary_state=ready/"
                "report_readiness=none while /workflow/status reports "
                "blocked. Was EPIC-019 AC19.2.7."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_2_7_events_session_summary_agrees_with_status_when_blocked"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 32: workflow-inbox — backend halves of the event inbox
        # sync + upload-first home contract (was EPIC-019 AC19.3.1-2/
        # AC19.4.1, migration closeout continuation, #1663 / #1712); the
        # frontend halves (AC19.3.3-8) stay in EPIC-019 ──
        ACRecord(
            id="AC-platform.32.1",
            statement=(
                "Deterministic sync refreshes mutable derived event fields "
                "for all of a user's statements without duplicating events "
                "or resetting lifecycle state. Was EPIC-019 AC19.3.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.32.2",
            statement=(
                "Workflow status uses one aggregate count query and only "
                "fetches a representative event for the winning branch. "
                "Was EPIC-019 AC19.3.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_3_2_workflow_status_uses_single_aggregate_for_badge_counts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.32.3",
            statement=(
                "EPIC-019 and the workflow-events SSOT define /dashboard as "
                "the upload-first authenticated home, with dashboard "
                "metrics as secondary analytics. Was EPIC-019 AC19.4.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_4_1_upload_first_home_ssot_documents_dashboard_contract"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 33: workflow-session — WorkflowSession backend model,
        # migration, and concurrency-safe get-or-create (was EPIC-019
        # AC19.8.1/.2/.3/.9, migration closeout continuation, #1663 /
        # #1712); the frontend/IA halves (AC19.8.4-8) stay in EPIC-019 ──
        ACRecord(
            id="AC-platform.33.1",
            statement=(
                "WorkflowSession is documented as the EPIC-019 product "
                "object; AI chat sessions are documented as /chat UI state "
                "outside workflow ownership. Was EPIC-019 AC19.8.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_8_1_workflow_session_ssot_separates_chat_sessions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.33.2",
            statement=(
                "The backend model and migration define workflow_sessions, "
                "an explicit workflow_session_status_enum, and a "
                "nullable legacy-safe workflow_events.session_id with "
                "session timeline indexes. Was EPIC-019 AC19.8.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_8_2_workflow_session_model_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.33.3",
            statement=(
                "GET /workflow/status returns an active session summary "
                "and GET /workflow/events returns session-scoped event "
                "timeline metadata. Was EPIC-019 AC19.8.3."
            ),
            test=(
                "apps/backend/tests/api/test_workflow_router.py"
                "::test_AC19_8_3_workflow_status_and_events_expose_session_timeline"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.33.4",
            statement=(
                "Concurrent GET /workflow/status and GET /workflow/events "
                "reads create or reuse the synthetic active workflow "
                "session without duplicate-key 500s. Was EPIC-019 AC19.8.9."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_8_9_active_workflow_session_get_or_create_is_concurrency_safe"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 34: lightweight-derivation — workflow-event derivation
        # boundaries and derived events from review/report/reconciliation
        # state (was EPIC-019 AC19.12.1-4, migration closeout continuation,
        # #1663 / #1712); the frontend half (AC19.12.5) stays in EPIC-019 ──
        ACRecord(
            id="AC-platform.34.1",
            statement=(
                "EPIC-019 and the workflow-events SSOT define lightweight "
                "user-facing derivation boundaries, keep low-level source/"
                "review/reconciliation/report facts in normalized owner "
                "tables, and exclude low-level event logging from workflow "
                "events. Was EPIC-019 AC19.12.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_1_lightweight_derivation_boundary_is_documented"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.34.2",
            statement=(
                "Workflow sync derives review-required and "
                "review-completed user action events from existing review "
                "state without duplicating events or resetting read/"
                "archive lifecycle. Was EPIC-019 AC19.12.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.34.3",
            statement=(
                "Workflow sync derives report-blocked and report-ready "
                "events from package readiness without duplicating "
                "report-readiness financial logic. Was EPIC-019 AC19.12.3."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.34.4",
            statement=(
                "Workflow sync derives reconciliation and Processing "
                "account blocker events only when they affect user action "
                "or trusted report readiness. Was EPIC-019 AC19.12.4."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_4_readiness_blocker_events_are_user_action_scoped"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 35: dedupe-safety — workflow-event dedupe is
        # transaction-safe under concurrency (was EPIC-019 AC19.14,
        # migration closeout continuation, #1663 / #1712) ──
        ACRecord(
            id="AC-platform.35.1",
            statement=(
                "Two concurrent upserts of the same (user_id, dedupe_key) "
                "workflow event both succeed instead of one raising "
                "UniqueViolationError. Was EPIC-019 AC19.14.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_14_1_concurrent_upsert_same_dedupe_key_does_not_500"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.35.2",
            statement=(
                "When the same (user_id, dedupe_key) is inserted twice "
                "within one session, the duplicate insert does not poison "
                "the outer request transaction. Was EPIC-019 AC19.14.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_14_2_duplicate_insert_does_not_poison_outer_transaction"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-platform.35.3",
            statement=(
                "Concurrent sync_workflow_events_for_user runs over the "
                "same source state do not error or duplicate events. Was "
                "EPIC-019 AC19.14.3."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_14_3_sync_tolerates_concurrent_event_creation"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 36: unified-inbox — backend halves of the EPIC-022
        # unified notification inbox (was EPIC-022 AC22.2.2/.5/AC22.4.1,
        # migration closeout continuation, #1663 / #1712); the frontend
        # halves stay in EPIC-022 ──
        ACRecord(
            id="AC-platform.36.1",
            statement=(
                "A Stage 1 review-required workflow event deep-links to "
                "that statement's review page (/statements/{id}/review). "
                "Was EPIC-022 AC22.2.2."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.36.2",
            statement=(
                "Review-required events are deduplicated by (user, "
                "dedupe_key) so re-syncing the same statement does not "
                "duplicate the inbox card. Was EPIC-022 AC22.2.5."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-platform.36.3",
            statement=(
                "A user with pending Stage 2 reconciliation matches gets a "
                "reconciliation-review attention event in the workflow "
                "inbox that deep-links to /reconciliation/review-queue "
                "(proven from match state through to event). Was EPIC-022 "
                "AC22.4.1."
            ),
            test=(
                "apps/backend/tests/workflow/test_workflow_events.py"
                "::test_AC22_4_1_pending_stage2_match_surfaces_reconciliation_review_event"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
