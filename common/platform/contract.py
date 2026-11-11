"""PackageContract for ``platform``."""

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
AppConfig BASE_CURRENCY_KEY BaseAppException DomainEvent EventBus Outbox OutboxEventBus
OutboxRelay PingStateResponse OutboxRepository PingState RateLimitConfig RateLimitState
RateLimiter RecordingEventBus SubscriberRegistry TimestampMixin UUIDMixin UserOwnedMixin
get_client_ip get_owned_or_404 paginate raise_bad_request raise_conflict
raise_gateway_timeout raise_internal_error raise_not_found raise_service_unavailable
raise_too_large raise_too_many_requests raise_unauthorized platform_system_router
validate_internal_action_href
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
@-
relay-dispatches-once-post-commit|The relay reads committed pending rows in id order, dispatches each to subscribed handlers, marks it published.|$be/platform/test_relay.py::test_second_run_does_not_redispatch_published
"""
    ),
    roadmap=acs(
        "platform",
        """
@$be/platform/test_relay.py
1.2||test_run_once_dispatches_and_marks_published
1.3||test_redelivery_of_pending_is_idempotent_safe|P1
@$be/infra/test_exceptions.py|P1
21.1||test_base_app_exception_has_error_id
21.2||test_base_app_exception_has_status_code
21.3||test_base_app_exception_is_subclass_of_exception
21.4||test_base_app_exception_raise_and_catch
21.5||test_base_app_exception_handler_returns_structured_json
@$be/infra/test_rate_limit.py|P1
23.1||test_global_rate_limit_middleware_exempts_health
23.2||test_global_rate_limit_middleware_blocks_after_limit
23.3||test_global_rate_limit_middleware_allows_normal_requests
23.4||test_global_rate_limit_middleware_exempts_docs
@$be/api/test_typed_contract_sweep.py|P1
27.1||test_AC12_27_1_http_error_has_structured_error_id
27.2||test_AC12_27_2_openapi_declares_error_response_contract
@$t/test_generate_openapi_spec.py|P2
28.1||test_AC12_28_1_generator_emits_types_from_openapi
28.2||test_AC12_28_2_staleness_gate_detects_drift
@$be/api/test_api_surface_consistency.py|P1
29.1||test_AC12_29_1_status_codes_use_constants_and_async_uses_202
29.2||test_AC12_29_2_named_unbounded_endpoints_are_bounded
29.3||test_AC12_29_3_pagination_convention_is_enforced
29.4||test_AC12_29_4_no_route_or_tag_collisions
29.5||test_AC12_29_5_deprecated_statement_decision_endpoints_removed
29.6||test_AC12_29_6_verb_in_path_urls_renamed_to_resources
29.7||test_AC_platform_29_7_every_get_limit_has_an_upper_bound
29.8||test_AC_platform_29_8_delivery_helpers_have_one_honest_home
29.9||test_AC_platform_29_9_report_wire_shape_and_policy_are_single
@$be/workflow/test_workflow_events.py
30.1||test_AC19_1_1_workflow_event_ssot_registers_manifest_owner
30.2||test_AC19_1_2_workflow_event_model_contract
30.3||test_AC19_1_3_workflow_event_schema_rejects_external_action_href
30.4||test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic
30.5||test_AC19_1_5_workflow_event_lifecycle_is_user_isolated
31.7||test_AC19_2_7_events_session_summary_agrees_with_status_when_blocked
32.1||test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset
32.2||test_AC19_3_2_workflow_status_uses_single_aggregate_for_badge_counts
32.3||test_AC19_4_1_upload_first_home_ssot_documents_dashboard_contract
33.1||test_AC19_8_1_workflow_session_ssot_separates_chat_sessions
33.2||test_AC19_8_2_workflow_session_model_contract
33.4||test_AC19_8_9_active_workflow_session_get_or_create_is_concurrency_safe
34.1||test_AC19_12_1_lightweight_derivation_boundary_is_documented
34.2|Workflow sync derives review-required and review-completed user action events from existing review state.|test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved
36.1|A Stage 1 review-required workflow event deep-links to that statement's detail page.|^|P1
36.2|Review-required events are deduplicated by.|^|P1
34.3||test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers
34.4||test_AC19_12_4_readiness_blocker_events_are_user_action_scoped
35.1||test_AC19_14_1_concurrent_upsert_same_dedupe_key_does_not_500
35.2||test_AC19_14_2_duplicate_insert_does_not_poison_outer_transaction
35.3||test_AC19_14_3_sync_tolerates_concurrent_event_creation
36.3||test_AC22_4_1_pending_stage2_match_surfaces_reconciliation_review_event|P1
@$be/api/test_workflow_router.py
31.1||test_AC19_2_1_workflow_status_schema_contract
31.2||test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries
31.3||test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events
31.4||test_AC19_2_4_workflow_event_patch_is_user_scoped
31.5||test_AC19_2_5_workflow_reads_sync_derived_events_without_lifecycle_reset
31.6||test_AC19_2_6_workflow_router_and_ssot_document_compact_read_path
33.3||test_AC19_8_3_workflow_status_and_events_expose_session_timeline
@$fe/__tests__/workflowSurfaces.test.tsx
fe-ia-inbox.2|The header bell badge reflects review/reconciliation attention.|AC19.3.4 AC22.2.3 shows the header badge from compact workflow counts and hides counts when quiet|P1
fe-workflow.2|Header/app-shell badge reflects unread/action-required/blocked counts from the compact workflow API and stays quiet.|^
fe-ia-inbox.6||AC22.6.3 links the notification center to the full confidence-ranked attention queue|P1
fe-workflow.3||AC19.3.5 renders the upload-page status feed, inbox total, and lifecycle actions
fe-workflow.6||AC19.3.5 AC19.8.4 groups inbox events by workflow session timeline and supports lifecycle actions
fe-workflow.7||AC19.12.5 renders lightweight derived workflow events as user actions, not internal logs
fe-workflow.8||AC-platform.fe-workflow.8 requests upload-page workflow events in parallel with the status
fe-workflow.9||AC-platform.fe-workflow.9 folds the upload-page notices under one summary line|P1
@$fe/__tests__/reviewBackLinks.test.tsx|P1
fe-ia-inbox.4||AC22.5.3 BackLink defaults to the upload page
fe-ia-inbox.5||AC22.5.4 the review surface heading uses plain language, not internal jargon
@$be/platform/test_outbox_atomicity.py
1.1||test_commit_leaves_exactly_one_outbox_row
@$be/platform/test_contract.py|P1
1.4||test_platform_package_passes_governance_gate
@$be/counter/test_outbox_emit.py|P1
1.5||test_record_increment_writes_incremented_atomically
@$be/platform/test_href.py|P1
1.6||test_AC_platform_1_6_reporting_and_workflow_schemas_use_the_platform_check
@$be/infra/test_epic_001_contracts.py
19.1||test_epic_001_moon_workspace_configs_exist
@$be/portfolio/test_brokerage_import_error_contract.py|P1
27.4||test_AC_platform_27_4_brokerage_import_errors_carry_request_id
@$fe/__tests__/unifiedInbox.test.tsx|P1
fe-ia-inbox.1||AC22.2.1 surfaces Stage 1 review and Stage 2 reconciliation attention with deep links
@apps/frontend/playwright/unified-inbox.spec.ts|P1
fe-ia-inbox.3||${label} surfaces review attention in the upload workflow notices with deep links
@$fe/__tests__/workflowApi.test.ts
fe-workflow.1||AC19.3.3 fetches typed workflow status through lib/api-client.ts
@apps/frontend/playwright/workflow-notifications.spec.ts
fe-workflow.4||${scenario.name} shows workflow badge, inbox, and the Home action banner
@$fe/__tests__/homeActionBanner.test.tsx
fe-workflow.5||AC-platform.fe-workflow.5 shows the next-action summary, and the workflow-state sentence once when the summary is empty
@$t/test_platform_package.py
boundary.1||test_AC_platform_boundary_1_outbox_public_language_is_not_an_orm_row
""",
    ),
)
