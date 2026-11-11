"""Machine-checkable PackageContract for ``advisor``."""

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
    depends_on="""
audit ledger llm observability platform portfolio pricing reconciliation reporting
workflow
""".split(),
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
ChatSessionStatus ChatStream DISCLAIMER_EN DISCLAIMER_ZH ResponseCache
StreamRedactor build_refusal detect_language ensure_disclaimer get_ai_advisor_prompt
is_non_financial is_prompt_injection is_sensitive_request is_write_request
normalize_question redact_sensitive register_fx_pairs_read
""".split(),
    events=[],
    invariants=[],
    roadmap=acs(
        "advisor",
        """
@$be/ai/test_ai_advisor_service.py|P0|done|property
guardrail.1|A write/mutation request is detected by `is_write_request` and refused.|test_chat_stream_refusal_branches|-|non-goals-not-robo-advisor
guardrail.2|Prompt-injection attempts and sensitive-data requests are detected and refused.|test_safety_filters
session.1|A `ChatSession` is owned by exactly one user.|test_get_or_create_session_with_existing_session|P1::open
cache.1|Identical questions from the same user against the same financial context and model return the cached response (deterministic dedup by `normalize_question + sha256 + model_key`).|test_chat_stream_uses_cached_response|P2
guardrail.3|A non-financial query is detected by `is_non_financial`, verified alongside the other three guardrail predicates in the same assertion set.|test_safety_filters
guardrail.4|Legitimate financial queries pass all four guardrail predicates.|test_safety_filters_negative_cases
guardrail.5|`ensure_disclaimer` appends the localized disclaimer exactly once to a response that does not already contain it.|test_ensure_disclaimer_appends_once
guardrail.6|`ensure_disclaimer` is a no-op.|test_ensure_disclaimer_respects_existing
guardrail.7|`StreamRedactor` masks a sensitive numeric sequence even.|test_stream_redactor_masks_sensitive_sequences
guardrail.8|`StreamRedactor` buffers a short tail chunk.|test_stream_redactor_flushes_tail|P1
guardrail.9|`StreamRedactor.flush` returns an empty string.|test_stream_redactor_flush_empty|P1
guardrail.10|`build_refusal` defaults to the non-financial-topic refusal message and still appends the disclaimer.|test_build_refusal_defaults_to_non_financial
guardrail.11|`redact_sensitive` masks a detected card-like numeric sequence in free text with `[REDACTED]`, removing the original digits from the output.|test_redact_sensitive
session.2|`_get_or_create_session` raises `AIAdvisorError`.|test_get_or_create_session_missing_raises
session.3|`_load_history` skips SYSTEM-role messages.|test_load_history_skips_system_messages
session.4|`_record_message` sets the session's `title` from the first recorded message's content.|test_record_message_sets_title
session.7|`_record_message` swallows an exception raised by `db.refresh`.|test_record_message_refresh_exception_logs_warning|P1
context.2|`get_financial_context` degrades gracefully.|test_get_financial_context_handles_report_errors
context.3|`get_financial_context` scopes monthly income/expenses, unmatched count, pending-review count.|test_get_financial_context_filters_by_user
context.4|Prompt construction surfaces the structured `advisor_context`/`advisor_suggestions` facts verbatim and injects an explicit instruction that blocked report readiness is not trusted and that stale/unreviewed/unsupported/manual-trusted data must keep its stated limitation.|test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state
context.7|When the current calendar month has zero income and expenses but earlier posted income or expense activity exists, `get_financial_context` anchors `monthly_income`, `monthly_expenses`.|test_AC_advisor_context_7_financial_context_anchors_to_latest_active_month|P1
cache.2|`ResponseCache` entries expire per their configured TTL.|test_response_cache_ttl|P1
cache.3|`ResponseCache.prune` removes already-expired entries from the store.|test_response_cache_prune|P1
stream.1|`_stream_openrouter` streams from the large role of the infra2 SDK with its high reasoning effort, yielding chunks tagged with that model.|test_stream_openrouter_uses_the_large_role_with_high_reasoning
stream.2|`_stream_openrouter` raises `AIStreamError`.|test_stream_openrouter_does_not_fall_back_to_another_model
stream.3|`chat_stream` raises `AIAdvisorError`.|test_chat_stream_requires_api_key
stream.4|`_stream_and_store` appends the disclaimer to the assembled response and records it in the `ResponseCache` under the request's cache key once the stream completes.|test_stream_and_store_records_response
stream.5|`_stream_and_store` translates an underlying error from `_stream_openrouter` into `AIAdvisorError`.|test_stream_and_store_raises_on_stream_error
stream.6|On a cache miss, `chat_stream` returns a `ChatStream` with `cached=False` whose stream is backed by `_stream_and_store`'s live pipeline.|test_chat_stream_success_path_uses_stream
stream.7|`_stream_openrouter` tries a caller-supplied `preferred_model`.|test_stream_openrouter_with_preferred_model|P1
stream.8|`_stream_openrouter` converts a `ValueError`/`TypeError` raised inside `_stream_model` into `AIAdvisorError` with an 'Internal error.|test_stream_openrouter_raises_on_programming_error|P1
stream.9|`_stream_model` proxies chunks yielded by the underlying `stream_ai_chat` transport call unchanged, chunk-by-chunk.|test_stream_model_yields_chunks|P1
textutil.1|`normalize_question` strips leading/trailing whitespace and lowercases the question text.|test_normalize_question|P1
textutil.3|`AIAdvisorService._chunk_text` splits a string into fixed-size pieces of the requested size.|test_chunk_text_splits_text|P1
grounding.2|A grounded chat answer that has pending reconciliation review context exposes a 'Review N' action deep-link to the review queue.|test_AC22_14_3_chat_grounding_metadata_links_pending_review_without_write_actions|P1
2598.1|_get_financial_summary_context derives balance_sheet_confidence_tier and income_statement_confidence_tier from report line provenance.|test_AC_advisor_2598_1_financial_context_derives_confidence_tiers_from_line_provenance|P1
@$be/ai/test_chat_router.py|P0|done|property
session.5|`DELETE /api/chat/session/{id}` marks the resolved `ChatSession.status` as DELETED and commits.|test_delete_session_success
session.6|`DELETE /api/chat/session/{id}` returns 404.|test_delete_session_not_found
language.1|`detect_language` classifies Chinese-language input as 'zh'.|test_detect_language_chinese
language.2|`detect_language` classifies English-language input as 'en'.|test_detect_language_english
language.3|The chat-suggestions endpoint auto-detects Chinese from the caller's `message` text and returns Chinese-language suggestions.|test_chat_suggestions_auto_detect_zh
language.4|The chat-suggestions endpoint auto-detects English from the caller's `message` text and returns English-language suggestions.|test_chat_suggestions_auto_detect_en
suggestions.1|`GET /api/chat/suggestions?language=zh` returns Chinese-language quick-question suggestions.|test_chat_suggestions_zh
suggestions.2|`GET /api/chat/suggestions?language=en` returns English-language quick-question suggestions.|test_chat_suggestions_en
suggestions.3|The chat-suggestions endpoint.|test_AC21_3_1_chat_suggestions_include_structured_advisor_facts
api.1|`POST /api/chat` returns HTTP 503 with a 'temporarily unavailable' message.|test_chat_error_api_key_unavailable
api.2|`POST /api/chat` returns HTTP 404.|test_chat_error_session_not_found
api.3|`POST /api/chat` returns HTTP 400.|test_chat_error_bad_request
api.4|`POST /api/chat` sets the `X-Model-Name` response header to the model that actually served the response.|test_chat_with_model_name_header
api.5|`POST /api/chat` omits the `X-Model-Name` header entirely.|test_chat_without_model_name_header
grounding.1|POST /api/chat exposes structured grounding metadata for personal-data answers.|test_AC22_14_1_chat_response_exposes_grounding_metadata_header|P1
2555.1|POST /api/chat primes the first stream chunk.|test_AC_advisor_2555_1_pre_first_chunk_stream_error_returns_503_not_empty_200|P1
@$be/ai/test_streaming_contract.py|P0|done|property
envelope.1|`ChatStreamEnvelope` with only a `session_id` set builds a text/plain response exposing just `X-Session-Id`, with `Access-Control-Expose-Headers` listing exactly that one header.|test_AC6_33_1_chat_envelope_minimal_headers
envelope.2|`ChatStreamEnvelope` with a model name and non-empty `ChatResponseMetadata` exposes `X-Model-Name` and a JSON `X-Advisor-Metadata` header.|test_AC6_33_2_chat_envelope_includes_model_and_metadata_headers
envelope.3|`ChatStreamEnvelope` omits `X-Advisor-Metadata`.|test_AC6_33_3_chat_envelope_omits_empty_advisor_metadata
envelope.4|Constructing a `ChatStreamEnvelope` with advisor metadata that violates the `ChatResponseMetadata` schema raises a Pydantic `ValidationError`.|test_AC6_33_4_chat_envelope_rejects_invalid_advisor_metadata
envelope.5|`chat_message` builds its `StreamingResponse` from `ChatStreamEnvelope.to_headers`.|test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers
@$fe/__tests__/ChatPageClient.test.tsx|P2
fe-chat.2|Chat page client enforces disclaimer consent and passes initial prompt into chat panel.|AC16.19.5 AC16.20.2 shows consent modal when not accepted
fe-chat.3|Chat page client renders primary navigation links and first-class conversational IA.|AC16.19.6 AC16.20.2 renders navigation links
@$fe/__tests__/chatPanelComponent.test.tsx|P2
fe-chat.4|Chat panel sends streaming responses, loads suggestions/history.|AC16.20.5 loads suggestions/history and streams reply
fe-chat.5|Handles missing stream reader.|AC16.20.7 handles missing stream reader|P1
fe-chat.6|ChatPanel renders modern conversational bubbles with avatar and right-aligned user bubble, avoiding full-width rectangular bars.|AC-advisor.fe-chat.6 renders modern conversational bubbles with avatar
fe-chat.7|ChatPanel formats structured markdown tables, lists.|AC-advisor.fe-chat.7 formats structured markdown tables and bold text
fe-chat.8|ChatPanel input area provides auto-growing textarea, circular send button.|AC-advisor.fe-chat.8 input area supports auto-grow and circular send
fe-ia-chat.1|`ChatPanel` renders assistant-answer citations as safe internal links and shows pending-action chips.|AC22.14.2 AC22.14.3 renders grounded answer citations and pending action chips|P1
fe-remainder-chat.1|`/chat` is a simple AI utility page with model selector, active conversation.|AC19.8.6 shows chat sessions inside the AI page without workflow ownership|P1
fe-remainder-chat.3|Chat and dashboard surfaces expose contextual Ask AI links that seed a scoped prompt.|AC21.3.3 test_AC21_3_3_chat_panel_renders_contextual_advisor_brief|P0
@-|P1|done|property
fx-port.1|Advisor FX pair and conversion registrations expose exact async protocol signatures.|$t/test_s3_pr_d_structure.py::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders|P0:-
guardrail.13|`StreamRedactor` withholds emission of a chunk smaller than its configured tail size, accumulating it in an internal buffer.|$be/infra/test_infra_edge_cases.py::test_stream_redactor_small_chunks
context.1|Advisor answers are grounded only in the user's bounded read context.|$be/ai/test_advisor_bounded_context.py::test_AC_advisor_context_1_context_is_exactly_the_bounded_read_set
guardrail.12|The bank-account PII detector skips date-like and zero-heavy numeric sequences, flagging only genuine account-like numbers, to avoid over-redacting ordinary numbers.|$be/ai/test_pii_redaction.py::test_detect_pii_skips_date_like_and_zero_heavy_numbers
context.5|On real data, `get_advisor_context` and `get_financial_context` return the same facts and suggestions as.|$be/ai/test_advisor_context_equivalence.py::test_AC_advisor_context_5_context_and_suggestions_equal_the_pre_change_output
context.6|At 1000 journal entries, after the app shell read the workflow status, `GET /api/chat/suggestions?include_structured=true` and the `/chat` answer context each issue fewer than 60 SQL statements.|$be/ai/test_advisor_year_scale_budget.py::test_AC_advisor_context_6_structured_suggestions_within_sql_budget_at_year_scale
txn.1|The advisor reads other domains only.|$t/test_advisor_package.py::test_AC_advisor_txn_1_reads_only_published_interfaces|P0
grounding.3|On a pinned staging deployment, one isolated user records an opening balance of 10,000.00 and approves one statement of the current month with a salary of +5,000.00 and a rent of -1,500.00.|$e2e/test_assistant_chat_journey.py::test_assistant_answers_from_the_data_of_the_user|P0|decision-filter-accuracy-auditability
application-layer.1|Scale coverage and confidence work is explicitly routed to existing EPICs and issues.|$t/test_application_ai_advisor_epic021_contract.py::test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics
fe-chat.1|Chat page renders advisor client within suspense boundary.|$fe/__tests__/chatPage.test.tsx::AC16.16.3 renders advisor client|P2:-
fe-remainder-chat.2|Advisor Brief renders blocked, ready, review-required.|$fe/__tests__/advisorBrief.test.tsx::AC21.3.2 test_AC21_3_2_advisor_brief_renders_structured_cards_and_safe_routes|P0:-
fe-remainder-chat.4|Advisor Brief keeps desktop and mobile layouts free of horizontal overflow.|apps/frontend/playwright/advisor-brief.spec.ts::${scenario.name} advisor-brief desktop and mobile layouts avoid horizontal overflow|:-
""",
    ),
    concepts=concepts(
        """
ai_advisor_policy|common/advisor/readme.md|AI advisor application-layer contract, prompt policy, context scope, and safety controls.|common/llm/ai.md,common/reporting/reporting.md,common/workflow/workflow-events.md,apps/backend/src/extraction/base/source_capability.py,common/pricing/market_data.md,docs/project/EPIC-021.application-ai-advisor.md|-|ai|concept
"""
    ),
)
