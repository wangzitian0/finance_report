"""Machine-checkable PackageContract for ``platform``."""

from __future__ import annotations

from common.meta.package_contract import ContextScope, PackageContract, acs, invs, units

CONTRACT = PackageContract(
    name="platform",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles="base extension".split(),
    implementations={"be": "apps/backend/src/platform", "fe": None},
    context=ContextScope(
        purpose="Provide reusable runtime infrastructure for transactional domain-event delivery, request-rate protection.",
        in_scope=[
            "Transactional outbox and generic event dispatch.",
            "Process-wide request rate limiting.",
            "Shared structural ORM mixins.",
        ],
        out_of_scope=[
            "Domain workflow and saga semantics.",
            "Business-domain state and policy.",
            "HTTP route ownership and application composition.",
        ],
    ),
    units=units(
        """
DomainEvent|ev|base/event.py
validate_internal_action_href|fac|base/href.py
Outbox|ent|base/outbox.py
@bus|extension/bus.py|OutboxEventBus RecordingEventBus
OutboxRelay|bus|extension/relay.py
RateLimiter|svc|extension/rate_limit.py
EventBus|repo|base/bus.py|extension/bus.py
OutboxRepository|repo|base/outbox.py|extension/sql.py
"""
    ),
    interface="""
AppConfig BASE_CURRENCY_KEY BaseAppException DomainEvent EventBus Outbox
OutboxEventBus OutboxRelay PingStateResponse OutboxRepository PingState
RateLimitConfig RateLimitState RateLimiter RecordingEventBus SubscriberRegistry
TimestampMixin UUIDMixin UserOwnedMixin get_client_ip get_owned_or_404 paginate
raise_bad_request raise_conflict raise_gateway_timeout raise_internal_error
raise_not_found raise_service_unavailable raise_too_large raise_too_many_requests
raise_unauthorized platform_system_router validate_internal_action_href
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_platform_package.py
converges-by-layer|The package converges into base/ (pure core) + extension/ (edges).|test_platform_converges_by_layer
repository-split|The event-bus and outbox-repository ports each split into a base port + an extension adapter.|test_platform_repository_split
base-layer-pure|The base/ layer never imports the package's own extension/ or the ORM.|test_platform_base_layer_is_pure
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_platform_interface_equals_published_language
passes-own-governance-gate|Check_package_contract validates platform with no violations.|test_platform_package_contract_gate_passes
@-
outbox-write-is-atomic|Publishing through the OutboxEventBus writes the event in the caller's transaction.|$be/platform/test_outbox_atomicity.py::test_rollback_leaves_no_outbox_row
relay-dispatches-once-post-commit|The relay reads committed pending rows in id order, dispatches each to subscribed handlers, marks it published.|$be/platform/test_relay.py::test_second_run_does_not_redispatch_published
"""
    ),
    roadmap=acs(
        "platform",
        """
@$be/platform/test_relay.py|P0
1.2|OutboxRelay.run_once reads committed pending rows in enqueue order, dispatches each to its subscribed handlers with the rehydrated DomainEvent.|test_run_once_dispatches_and_marks_published
1.3|Dispatch is at-least-once.|test_redelivery_of_pending_is_idempotent_safe|P1
@$be/infra/test_exceptions.py|P1
21.1|BaseAppException stores the error_id attribute.|test_base_app_exception_has_error_id
21.2|BaseAppException stores the status_code attribute.|test_base_app_exception_has_status_code
21.3|BaseAppException is a subclass of Exception.|test_base_app_exception_is_subclass_of_exception
21.4|BaseAppException can be raised and caught with its fields intact.|test_base_app_exception_raise_and_catch
21.5|The BaseAppException handler serializes error_id and status_code into a structured JSON response.|test_base_app_exception_handler_returns_structured_json
@$be/infra/test_rate_limit.py|P1
23.1|The global rate-limit middleware exempts /health.|test_global_rate_limit_middleware_exempts_health
23.2|The global rate-limit middleware returns 429 with a Retry-After header.|test_global_rate_limit_middleware_blocks_after_limit
23.3|The global rate-limit middleware allows normal requests within the limit.|test_global_rate_limit_middleware_allows_normal_requests
23.4|The global rate-limit middleware exempts /docs.|test_global_rate_limit_middleware_exempts_docs
@$be/api/test_typed_contract_sweep.py|P1
27.1|An HTTPException-derived 404 returns a structured body with an error_id.|test_AC12_27_1_http_error_has_structured_error_id
27.2|OpenAPI declares the shared ErrorResponse and references it for the common 4xx errors.|test_AC12_27_2_openapi_declares_error_response_contract
@$t/test_generate_openapi_spec.py|P2
28.1|The generator emits the OpenAPI spec from the live FastAPI schema.|test_AC12_28_1_generator_emits_types_from_openapi
28.2|The --check staleness gate fails.|test_AC12_28_2_staleness_gate_detects_drift
@$be/api/test_api_surface_consistency.py|P1
29.1|Router status codes use status.HTTP_* constants.|test_AC12_29_1_status_codes_use_constants_and_async_uses_202
29.2|The named unbounded list endpoints accept bounded limit/offset with an enforced le=MAX_PAGE_LIMIT.|test_AC12_29_2_named_unbounded_endpoints_are_bounded
29.3|A single documented pagination convention is enforced.|test_AC12_29_3_pagination_convention_is_enforced
29.4|No two API operations collide on.|test_AC12_29_4_no_route_or_tag_collisions
29.5|The deprecated POST /statements/{id}/approve and /reject are removed.|test_AC12_29_5_deprecated_statement_decision_endpoints_removed
29.6|Verb-in-path action URLs are renamed to resource-style nouns.|test_AC12_29_6_verb_in_path_urls_renamed_to_resources
29.7|Every GET operation that exposes a limit query parameter declares an explicit finite upper bound, with no route exemptions.|test_AC_platform_29_7_every_get_limit_has_an_upper_bound
29.8|The API delivery surface has no duplicate DTO names or dishonest dependency defaults.|test_AC_platform_29_8_delivery_helpers_have_one_honest_home
29.9|Personal report package generation accepts one body shape only.|test_AC_platform_29_9_report_wire_shape_and_policy_are_single
@$be/workflow/test_workflow_events.py|P0
30.1|The workflow-event SSOT registers event families, severity/actionability, lifecycle states, dedupe rules, internal action links, indexes.|test_AC19_1_1_workflow_event_ssot_registers_manifest_owner
30.2|The backend model defines a user-scoped workflow_events read model with explicit enum names, lifecycle status, UNIQUE.|test_AC19_1_2_workflow_event_model_contract
30.3|Pydantic schemas validate the workflow event contract and reject external action_href values.|test_AC19_1_3_workflow_event_schema_rejects_external_action_href
30.4|The workflow event service deterministically upserts a derived event from existing statement/upload state.|test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic
30.5|Workflow event reads and lifecycle changes are user isolated.|test_AC19_1_5_workflow_event_lifecycle_is_user_isolated
31.7|GET /workflow/events session summaries reuse the authoritative get_workflow_status derivation.|test_AC19_2_7_events_session_summary_agrees_with_status_when_blocked
32.1|Deterministic sync refreshes mutable derived event fields for all of a user's statements.|test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset
32.2|Workflow status uses one aggregate count query and only fetches a representative event for the winning branch.|test_AC19_3_2_workflow_status_uses_single_aggregate_for_badge_counts
32.3|The workflow-events SSOT defines `/` as the authenticated home, where `HomeActionBanner` shows one workflow or confirmation action.|test_AC19_4_1_upload_first_home_ssot_documents_dashboard_contract
33.1|WorkflowSession is documented as the EPIC-019 product object.|test_AC19_8_1_workflow_session_ssot_separates_chat_sessions
33.2|The backend model and migration define workflow_sessions, an explicit workflow_session_status_enum.|test_AC19_8_2_workflow_session_model_contract
33.4|Concurrent GET /workflow/status and GET /workflow/events reads create or reuse the synthetic active workflow session.|test_AC19_8_9_active_workflow_session_get_or_create_is_concurrency_safe
34.1|EPIC-019 and the workflow-events SSOT define lightweight user-facing derivation boundaries, keep low-level source/review/reconciliation/report facts in normalized owner tables.|test_AC19_12_1_lightweight_derivation_boundary_is_documented
34.2|Workflow sync derives review-required and review-completed user action events from existing review state.|test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved
34.3|Workflow sync derives report-blocked and report-ready events from package readiness.|test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers
34.4|Workflow sync derives reconciliation and Processing account blocker events only.|test_AC19_12_4_readiness_blocker_events_are_user_action_scoped
35.1|Two concurrent upserts of the same workflow event both succeed.|test_AC19_14_1_concurrent_upsert_same_dedupe_key_does_not_500
35.2|The duplicate insert does not poison the outer request transaction.|test_AC19_14_2_duplicate_insert_does_not_poison_outer_transaction
35.3|Concurrent sync_workflow_events_for_user runs over the same source state do not error or duplicate events.|test_AC19_14_3_sync_tolerates_concurrent_event_creation
36.1|A Stage 1 review-required workflow event deep-links to that statement's detail page.|test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved|P1
36.2|Review-required events are deduplicated by.|test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved|P1
36.3|A user with pending Stage 2 reconciliation matches gets a reconciliation-review attention event in the workflow inbox that deep-links to /reconciliation?tab=review-queue.|test_AC22_4_1_pending_stage2_match_surfaces_reconciliation_review_event|P1
@$be/api/test_workflow_router.py|P0
31.1|Workflow status schemas define stable primary state, next action, report readiness.|test_AC19_2_1_workflow_status_schema_contract
31.2|GET /workflow/status returns user-scoped empty, processing, needs-action, blocked.|test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries
31.3|GET /workflow/events returns bounded, user-scoped, deduplicated events, excludes archived events by default.|test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events
31.4|PATCH /workflow/events/{id} updates only the authenticated user's event lifecycle and returns 404 for missing or non-owned events.|test_AC19_2_4_workflow_event_patch_is_user_scoped
31.5|Status and events reads run a deterministic derived sync.|test_AC19_2_5_workflow_reads_sync_derived_events_without_lifecycle_reset
31.6|The workflow API router is mounted and documented in the workflow-events SSOT as the compact read path for later UI slices.|test_AC19_2_6_workflow_router_and_ssot_document_compact_read_path
33.3|GET /workflow/status returns an active session summary and GET /workflow/events returns session-scoped event timeline metadata.|test_AC19_8_3_workflow_status_and_events_expose_session_timeline
@$fe/__tests__/workflowSurfaces.test.tsx|P0
fe-ia-inbox.2|The header bell badge reflects review/reconciliation attention.|AC19.3.4 AC22.2.3 shows the header badge from compact workflow counts and hides counts when quiet|P1
fe-ia-inbox.6|The header notification center links to the full Needs Confirmation queue on `/audit`.|AC22.6.3 links the notification center to the full confidence-ranked attention queue|P1
fe-workflow.2|Header/app-shell badge reflects unread/action-required/blocked counts from the compact workflow API and stays quiet.|AC19.3.4 AC22.2.3 shows the header badge from compact workflow counts and hides counts when quiet
fe-workflow.3|Event inbox groups events by workflow session timeline, keeps blocked/action-required events prominent.|AC19.3.5 renders the upload-page status feed, inbox total, and lifecycle actions
fe-workflow.6|Notification drawer and Events page group timestamped events by workflow session.|AC19.3.5 AC19.8.4 groups inbox events by workflow session timeline and supports lifecycle actions
fe-workflow.7|Dashboard status feed and event inbox render lightweight derived events as user actions.|AC19.12.5 renders lightweight derived workflow events as user actions, not internal logs
fe-workflow.8|The workflow notices of `/upload` request workflow events in parallel with the workflow status.|AC-platform.fe-workflow.8 requests upload-page workflow events in parallel with the status
fe-workflow.9|The upload-page workflow notices fold under one summary line.|AC-platform.fe-workflow.9 folds the upload-page notices under one summary line|P1
@$fe/__tests__/reviewBackLinks.test.tsx|P1
fe-ia-inbox.4|Deep review and reconciliation surfaces render a back-link to the upload page.|AC22.5.3 BackLink defaults to the upload page
fe-ia-inbox.5|User-facing review-surface headings use plain language and do not expose internal "Stage 2" or raw score-band wording in their titles.|AC22.5.4 the review surface heading uses plain language, not internal jargon
@-|P0
1.1|The OutboxEventBus writes a domain event into the shared outbox table using the caller's AsyncSession.|$be/platform/test_outbox_atomicity.py::test_commit_leaves_exactly_one_outbox_row
1.4|The platform package converges into the base/extension layering and its published language equals contract.interface.|$be/platform/test_contract.py::test_platform_package_passes_governance_gate|P1
1.5|Counter.record_increment bumps the per- tally and enqueues a counter.Incremented event into the shared outbox in the SAME transaction.|$be/counter/test_outbox_emit.py::test_record_increment_writes_incremented_atomically|P1
1.6|The reporting and workflow schemas share one internal action-href check from platform.base.|$be/platform/test_href.py::test_AC_platform_1_6_reporting_and_workflow_schemas_use_the_platform_check|P1
19.1|The moon workspace configuration files exist.|$be/infra/test_epic_001_contracts.py::test_epic_001_moon_workspace_configs_exist
27.4|Each error response of `POST /statements/{id}/brokerage/import` carries `error_id` and the request id in the body field `request_id` and in the `X-Request-ID` header.|$be/portfolio/test_brokerage_import_error_contract.py::test_AC_platform_27_4_brokerage_import_errors_carry_request_id|P1
fe-ia-inbox.1|The unified inbox surfaces Stage 1 source-review and Stage 2 reconciliation-review attention as cards.|$fe/__tests__/unifiedInbox.test.tsx::AC22.2.1 surfaces Stage 1 review and Stage 2 reconciliation attention with deep links|P1
fe-ia-inbox.3|Desktop and mobile smoke covers the unified inbox with review attention.|apps/frontend/playwright/unified-inbox.spec.ts::${label} surfaces review attention in the upload workflow notices with deep links|P1
fe-workflow.1|Frontend exposes typed workflow API helpers.|$fe/__tests__/workflowApi.test.ts::AC19.3.3 fetches typed workflow status through lib/api-client.ts
fe-workflow.4|Desktop and mobile Playwright smoke covers the workflow badge, the inbox and the Home action banner.|apps/frontend/playwright/workflow-notifications.spec.ts::${scenario.name} shows workflow badge, inbox, and the Home action banner
fe-workflow.5|The Home action banner shows `next_action.summary` of the workflow status as its text.|$fe/__tests__/homeActionBanner.test.tsx::AC-platform.fe-workflow.5 shows the next-action summary, and the workflow-state sentence once when the summary is empty
boundary.1|The public Outbox symbol is a pure base-layer event record.|$t/test_platform_package.py::test_AC_platform_boundary_1_outbox_public_language_is_not_an_orm_row
""",
    ),
)
