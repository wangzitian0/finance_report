"""PackageContract for ``advisor``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="advisor",
    status="active",
    tier="LLM-LED",
    depends_on="audit ledger llm observability platform portfolio pricing reconciliation reporting workflow".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/advisor", "fe": None},
    context=ContextScope(
        purpose="Provide a read-only application layer that aggregates trusted financial facts and lets the LLM explain them.",
        in_scope=[
            "Read-only cross-domain financial context aggregation.",
            "Advisor guardrails, citations, and streamed explanations.",
            "Advisor-owned chat session persistence.",
        ],
        out_of_scope=[
            "Ledger or other domain-state mutation.",
            "Ownership of portfolio, reporting, reconciliation, or workflow policy.",
            "LLM provider transport and model configuration.",
        ],
    ),
    relationships=rels(
        "advisor",
        """
audit|published-language|Formats audit-owned monetary values for explanations.
ledger|published-language|Reads ledger-owned account vocabulary and confidence ranking.
llm|published-language|Uses the LLM package facade for bound streaming and provider selection.
observability|published-language|Uses shared logging and error identifiers.
platform|composition|Uses cross-cutting persistence mixins and application-support vocabulary, not platform workflow ownership.
portfolio|projection|Reads portfolio summaries and active symbols as explanation context.
pricing|projection|Reads market-data scope status as explanation context.
reconciliation|projection|Reads reconciliation statistics without changing matching policy.
reporting|projection|Reads report summaries and readiness as deterministic grounding facts.
workflow|projection|Reads workflow status and next-action summaries for user guidance.
""",
    ),
    units=units(
        """
ChatSession|agg
ChatMessage|ent
@vo|-|ChatSessionStatus ChatMessageRole ChatStream ChatResponseMetadata AdvisorSuggestion ChatCitation
@svc|-|AIAdvisorService AdvisorGuardrails ResponseCache
AdvisorSceneBinding|fac
ChatSessionRepository|repo
ChatHistoryView|proj
"""
    ),
    interface="""
AIAdvisorError AIAdvisorService ChatMessage ChatMessageRole ChatSession
ChatSessionStatus ChatStream DISCLAIMER_EN DISCLAIMER_ZH ResponseCache StreamRedactor
build_refusal detect_language ensure_disclaimer get_ai_advisor_prompt is_non_financial
is_prompt_injection is_sensitive_request is_write_request normalize_question
redact_sensitive register_fx_pairs_read
""".split(),
    events=[],
    invariants=[],
    roadmap=acs(
        "advisor",
        """
@$be/ai/test_ai_advisor_service.py
guardrail.1||test_chat_stream_refusal_branches|-|non-goals-not-robo-advisor
guardrail.2|Prompt-injection attempts and sensitive-data requests are detected and refused.|test_safety_filters
guardrail.3|A non-financial query is detected by `is_non_financial`, verified alongside the other three guardrail predicates in the same assertion set.|^
session.1||test_get_or_create_session_with_existing_session|P1::open
cache.1||test_chat_stream_uses_cached_response|P2
guardrail.4||test_safety_filters_negative_cases
guardrail.5||test_ensure_disclaimer_appends_once
guardrail.6||test_ensure_disclaimer_respects_existing
guardrail.7||test_stream_redactor_masks_sensitive_sequences
guardrail.8||test_stream_redactor_flushes_tail|P1
guardrail.9||test_stream_redactor_flush_empty|P1
guardrail.10||test_build_refusal_defaults_to_non_financial
guardrail.11||test_redact_sensitive
session.2||test_get_or_create_session_missing_raises
session.3||test_load_history_skips_system_messages
session.4||test_record_message_sets_title
session.7||test_record_message_refresh_exception_logs_warning|P1
context.2||test_get_financial_context_handles_report_errors
context.3||test_get_financial_context_filters_by_user
context.4||test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state
context.7||test_AC_advisor_context_7_financial_context_anchors_to_latest_active_month|P1
cache.2||test_response_cache_ttl|P1
cache.3||test_response_cache_prune|P1
stream.1||test_stream_openrouter_uses_the_large_role_with_high_reasoning
stream.2||test_stream_openrouter_does_not_fall_back_to_another_model
stream.3||test_chat_stream_requires_api_key
stream.4||test_stream_and_store_records_response
stream.5||test_stream_and_store_raises_on_stream_error
stream.6||test_chat_stream_success_path_uses_stream
stream.7||test_stream_openrouter_with_preferred_model|P1
stream.8||test_stream_openrouter_raises_on_programming_error|P1
stream.9||test_stream_model_yields_chunks|P1
textutil.1||test_normalize_question|P1
textutil.3||test_chunk_text_splits_text|P1
grounding.2||test_AC22_14_3_chat_grounding_metadata_links_pending_review_without_write_actions|P1
2598.1||test_AC_advisor_2598_1_financial_context_derives_confidence_tiers_from_line_provenance|P1
@$be/ai/test_chat_router.py
session.5||test_delete_session_success
session.6||test_delete_session_not_found
language.1||test_detect_language_chinese
language.2||test_detect_language_english
language.3||test_chat_suggestions_auto_detect_zh
language.4||test_chat_suggestions_auto_detect_en
suggestions.1||test_chat_suggestions_zh
suggestions.2||test_chat_suggestions_en
suggestions.3||test_AC21_3_1_chat_suggestions_include_structured_advisor_facts
api.1||test_chat_error_api_key_unavailable
api.2||test_chat_error_session_not_found
api.3||test_chat_error_bad_request
api.4||test_chat_with_model_name_header
api.5||test_chat_without_model_name_header
grounding.1||test_AC22_14_1_chat_response_exposes_grounding_metadata_header|P1
2555.1||test_AC_advisor_2555_1_pre_first_chunk_stream_error_returns_503_not_empty_200|P1
@$be/ai/test_streaming_contract.py
envelope.1||test_AC6_33_1_chat_envelope_minimal_headers
envelope.2||test_AC6_33_2_chat_envelope_includes_model_and_metadata_headers
envelope.3||test_AC6_33_3_chat_envelope_omits_empty_advisor_metadata
envelope.4||test_AC6_33_4_chat_envelope_rejects_invalid_advisor_metadata
envelope.5||test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers
@$fe/__tests__/ChatPageClient.test.tsx|P2
fe-chat.2||AC16.19.5 AC16.20.2 shows consent modal when not accepted
fe-chat.3||AC16.19.6 AC16.20.2 renders navigation links
@$fe/__tests__/chatPanelComponent.test.tsx|P2
fe-chat.4||AC16.20.5 loads suggestions/history and streams reply
fe-chat.5||AC16.20.7 handles missing stream reader|P1
fe-chat.6||AC-advisor.fe-chat.6 renders modern conversational bubbles with avatar
fe-chat.7||AC-advisor.fe-chat.7 formats structured markdown tables and bold text
fe-chat.8||AC-advisor.fe-chat.8 input area supports auto-grow and circular send
fe-ia-chat.1||AC22.14.2 AC22.14.3 renders grounded answer citations and pending action chips|P1
fe-remainder-chat.1||AC19.8.6 shows chat sessions inside the AI page without workflow ownership|P1
fe-remainder-chat.3||AC21.3.3 test_AC21_3_3_chat_panel_renders_contextual_advisor_brief|P0
@$t/test_s3_pr_d_structure.py
fx-port.1||test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders
@$be/infra/test_infra_edge_cases.py|P1
guardrail.13||test_stream_redactor_small_chunks
@$be/ai/test_advisor_bounded_context.py|P1
context.1||test_AC_advisor_context_1_context_is_exactly_the_bounded_read_set
@$be/ai/test_pii_redaction.py|P1
guardrail.12||test_detect_pii_skips_date_like_and_zero_heavy_numbers
@$be/ai/test_advisor_context_equivalence.py|P1
context.5||test_AC_advisor_context_5_context_and_suggestions_equal_the_pre_change_output
@$be/ai/test_advisor_year_scale_budget.py|P1
context.6||test_AC_advisor_context_6_structured_suggestions_within_sql_budget_at_year_scale
@$t/test_advisor_package.py
txn.1||test_AC_advisor_txn_1_reads_only_published_interfaces
@$e2e/test_assistant_chat_journey.py
grounding.3||test_assistant_answers_from_the_data_of_the_user|-|decision-filter-accuracy-auditability
@$t/test_application_ai_advisor_epic021_contract.py|P1
application-layer.1||test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics
@$fe/__tests__/chatPage.test.tsx|P2
fe-chat.1||AC16.16.3 renders advisor client
@$fe/__tests__/advisorBrief.test.tsx
fe-remainder-chat.2||AC21.3.2 test_AC21_3_2_advisor_brief_renders_structured_cards_and_safe_routes
@apps/frontend/playwright/advisor-brief.spec.ts|P1
fe-remainder-chat.4||${scenario.name} advisor-brief desktop and mobile layouts avoid horizontal overflow
""",
    ),
    concepts=concepts(
        """
ai_advisor_policy|common/advisor/readme.md|AI advisor application-layer contract, prompt policy, context scope, and safety controls.|common/llm/ai.md,common/reporting/reporting.md,common/workflow/workflow-events.md,apps/backend/src/extraction/base/source_capability.py,common/pricing/market_data.md,docs/project/EPIC-021.application-ai-advisor.md|-|ai|concept
"""
    ),
)
