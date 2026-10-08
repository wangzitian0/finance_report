"""The ``advisor`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against.
The implementation physically lives at ``apps/backend/src/advisor`` (#1671
Wave B moved it out of ``apps/backend/src/services/ai_advisor``, absorbing
``prompts/ai_advisor.py`` and ``models/chat.py`` → ``orm/chat.py``; the
annualized-income schedule is reporting-owned (#567), so the
``interface == __all__`` check applies. Every ``invariants[].test`` and
``roadmap[].test`` must resolve to a real test function; ``depends_on`` must
not introduce a forbidden upward/sideways edge.

## What this package is

The application-layer AI financial advisor (EPIC-006 / EPIC-021): a
read-only conversational interface over the user's financial state.  The
advisor **never writes a ledger number** — it only reads from the user's
bounded context (reconciliation readiness, reporting summaries, portfolio
positions) and streams a grounded, cited, disclaimer-tagged response.

## Boundaries (confirmed at cutover, 2026-07-06; physical move 2026-07-12)

* **read-only guardrail** — every write/mutation request (`is_write_request`),
  every prompt-injection attempt (`is_prompt_injection`), and every
  sensitive-data request (`is_sensitive_request`) is refused before any LLM
  call is made.  The guardrail is also applied on the streaming path via
  `StreamRedactor`.  This is the package's non-negotiable invariant.
* **bounded context** — the advisor reads reconciliation/reporting/portfolio
  data as part of the same read-only request (the same `AsyncSession` as the
  chat-message insert — ``AC-advisor.txn.1``, now ``done``: every
  cross-domain read goes through the target package's *published* root
  (``ledger``/``platform``/``portfolio``/``pricing``/``reconciliation``/
  ``reporting``), and the one read whose owner still lives in the app
  remainder (the fx-pair composer) is injected through ``extension/app_reads.py``
  by the composition root — never a direct ``src.services.*`` import, never
  a cross-domain FK).  It never *writes* into the ledger.
* **LLM via ``llm``** — all provider calls go through the ``llm`` package
  (`SceneBinding` / `stream_ai_chat`); the advisor owns no raw HTTP surface.
* **session ownership** — a `ChatSession` is owned by exactly one user;
  once a session is closed it is immutable (the ARCHIVED lifecycle is a
  planned addition — `AC-advisor.session.1`).

## Cross-domain read edges

``depends_on`` mirrors the real import set: ``audit`` (money formatting),
``ledger`` (Account/AccountType/journal-line reads for category context —
registered as advisor's dependency once
#1675's D5 omnibus moved account.py/journal.py into ``ledger``, mid-flight of
this PR), ``llm`` (scene binding + streaming transport), ``observability``
(logging), ``platform`` (workflow status, HTTP error helpers), ``portfolio``
(summary, active symbols), ``pricing`` (market-data status),
``reconciliation`` (stats), ``reporting`` (balance sheet, income statement,
category breakdown, report-package readiness, income bucket classifier —
folded from the app remainder by #1666 while this PR was in flight).  All are
*read-only* edges; the advisor never writes into them.  The observed-FX-pair
composer is the
one remaining app-remainder read: its owner (``services/market_data_
scheduler.py``) hasn't folded yet (#1610), so the advisor consumes it
through the ``app_reads`` injection port; the edge gets declared when the
fold lands and the port collapses into a published-root import.  ``config``
was folded into ``runtime`` (#1669) — the flat ``src.config`` module is
shared infra, imported as the bare root.

## God-file → phase split (follow-up scope)

``extension/service.py`` (~860 lines) is still to be split into
``phases/{context_aggregation,prompt_construction,response_streaming}.py``;
``base/guardrails.py`` is already separate.  Until then the units are
declared *taxonomy-only* (``module=None``): the governance gate skips
placement checks for units without a module path, per the package model.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ac,
    ConceptRecord,
    ContextRelation,
    ContextScope,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="advisor",
    status="active",
    # LLM-LED: the advisor's correctness includes the LLM streaming path,
    # but the guardrail / session / cache ACs are fully deterministic
    # (property proofs); only the context-grounding ACs (future eval work)
    # carry proof_kind="eval".  Non-eval ACs keep proof_kind="property".
    tier="LLM-LED",
    # infra: llm (scene binding + streaming transport), observability
    # (logging), platform (workflow status, HTTP error helpers), audit
    # (money formatting).  Domain (same-layer, read-only, declared +
    # acyclic): ledger (AccountType + worst-confidence ranking for category
    # context — surfaced as a real edge only once #1675's D5 omnibus
    # registered `ledger` as the owner of account.py/journal.py, mid-flight
    # of this PR), portfolio, pricing,
    # reconciliation, reporting (#1666).  The observed-FX-pair composer is
    # still consumed through an app_reads injection port until #1610
    # physically folds it (see the module docstring).
    depends_on=[
        "audit",
        "ledger",
        "llm",
        "observability",
        "platform",
        "portfolio",
        "pricing",
        "reconciliation",
        "reporting",
        "workflow",
    ],
    context=ContextScope(
        purpose="Provide a read-only application layer that aggregates trusted financial facts and lets the LLM explain them without owning domain state.",
        in_scope=[
            "read-only cross-domain financial context aggregation",
            "advisor guardrails, citations, and streamed explanations",
            "advisor-owned chat session persistence",
        ],
        out_of_scope=[
            "ledger or other domain-state mutation",
            "ownership of portfolio, reporting, reconciliation, or workflow policy",
            "LLM provider transport and model configuration",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="audit",
            consumer="advisor",
            mode="published-language",
            reason="Formats audit-owned monetary values for explanations.",
        ),
        ContextRelation(
            provider="ledger",
            consumer="advisor",
            mode="published-language",
            reason="Reads ledger-owned account vocabulary and confidence ranking.",
        ),
        ContextRelation(
            provider="llm",
            consumer="advisor",
            mode="published-language",
            reason="Uses the LLM package facade for bound streaming and provider selection.",
        ),
        ContextRelation(
            provider="observability",
            consumer="advisor",
            mode="published-language",
            reason="Uses shared logging and error identifiers without owning observability policy.",
        ),
        ContextRelation(
            provider="platform",
            consumer="advisor",
            mode="composition",
            reason="Uses cross-cutting persistence mixins and application-support vocabulary, not platform workflow ownership.",
        ),
        ContextRelation(
            provider="portfolio",
            consumer="advisor",
            mode="projection",
            reason="Reads portfolio summaries and active symbols as explanation context.",
        ),
        ContextRelation(
            provider="pricing",
            consumer="advisor",
            mode="projection",
            reason="Reads market-data scope status as explanation context.",
        ),
        ContextRelation(
            provider="reconciliation",
            consumer="advisor",
            mode="projection",
            reason="Reads reconciliation statistics without changing matching policy.",
        ),
        ContextRelation(
            provider="reporting",
            consumer="advisor",
            mode="projection",
            reason="Reads report summaries and readiness as deterministic grounding facts.",
        ),
        ContextRelation(
            provider="workflow",
            consumer="advisor",
            mode="projection",
            reason="Reads workflow status and next-action summaries for user guidance.",
        ),
    ],
    roles=["base", "extension", "data"],
    units=[
        # ── base: aggregate root + entity + value language ──
        # ChatSession/ChatMessage + enums live in orm/chat.py (the package's
        # persistence models, #1675 D5 idiom); the schema-facing VOs live in
        # the lazy schemas hub. Declared taxonomy-only (module=None) so the
        # gate skips placement.
        Unit(name="ChatSession", kind=Kind.AGGREGATE_ROOT),
        Unit(name="ChatMessage", kind=Kind.ENTITY),
        # value objects — status/role enums + the public streaming/response shapes
        Unit(name="ChatSessionStatus", kind=Kind.VALUE_OBJECT),
        Unit(name="ChatMessageRole", kind=Kind.VALUE_OBJECT),
        Unit(name="ChatStream", kind=Kind.VALUE_OBJECT),
        Unit(name="ChatResponseMetadata", kind=Kind.VALUE_OBJECT),
        Unit(name="AdvisorSuggestion", kind=Kind.VALUE_OBJECT),
        Unit(name="ChatCitation", kind=Kind.VALUE_OBJECT),
        # ── extension: domain services + repository ──
        # Primary service: context aggregation → prompt construction → stream
        Unit(name="AIAdvisorService", kind=Kind.DOMAIN_SERVICE),
        # Guardrail suite: injection / write / sensitive detection + StreamRedactor
        Unit(name="AdvisorGuardrails", kind=Kind.DOMAIN_SERVICE),
        # Response cache (deterministic dedup by question + context hash + model)
        Unit(name="ResponseCache", kind=Kind.DOMAIN_SERVICE),
        # Factory: resolves the per-user advisor.chat SceneBinding from the
        # llm config source — declared taxonomy-only (depends on llm I/O).
        Unit(name="AdvisorSceneBinding", kind=Kind.FACTORY),
        # Repository — the one split block (mechanism B): port in base/,
        # adapter in extension/. Currently raw AsyncSession; the unscheduled
        # port/adapter split remains taxonomy-only until it receives an AC.
        Unit(name="ChatSessionRepository", kind=Kind.REPOSITORY),
        # ── data: read-model projections ──
        # chat history view (list of sessions + messages for the UI)
        Unit(name="ChatHistoryView", kind=Kind.PROJECTION),
    ],
    # BE implementation path (#1671 Wave B physical move).
    implementations={"be": "apps/backend/src/advisor", "fe": None},
    # Published language == src/advisor/__init__.py __all__ (gate-enforced).
    interface=[
        "AIAdvisorError",
        "AIAdvisorService",
        "ChatMessage",
        "ChatMessageRole",
        "ChatSession",
        "ChatSessionStatus",
        "ChatStream",
        "DISCLAIMER_EN",
        "DISCLAIMER_ZH",
        "ResponseCache",
        "StreamRedactor",
        "build_refusal",
        "detect_language",
        "ensure_disclaimer",
        "get_ai_advisor_prompt",
        "is_non_financial",
        "is_prompt_injection",
        "is_sensitive_request",
        "is_write_request",
        "normalize_question",
        "redact_sensitive",
        "register_fx_pairs_read",
    ],
    events=[],
    # Structural invariants: registered once the phase split settles and the
    # unit.module paths are set. The structural
    # boundary tests already exist (tests/tooling/test_advisor_package.py).
    invariants=[],
    # ── Roadmap: package-model AC registry ──
    # ACs migrated from EPIC-006 / EPIC-021 per Decision A (standard-
    # preserving move; the EPIC table rows are removed in a follow-up).
    # Original EPIC AC ids are kept as inline comments; existing test
    # functions keep their AC6_*/AC21_* names — the ``test=`` reference is
    # the resolvable anchor, not the function name.
    roadmap=[
        ac(
            "AC-advisor.fx-port.1",
            "Advisor FX pair and conversion registrations expose exact async protocol signatures without Callable[..., Any] erasure.",
            "tests/tooling/test_s3_pr_d_structure.py::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders",
        ),
        ac(
            "AC-advisor.guardrail.1",
            "A write/mutation request (create/post/delete/void/modify a journal or ledger entry) is detected by ``is_write_request`` and refused before any LLM call; the advisor never writes a ledger number.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_chat_stream_refusal_branches",
            proof_kind="property",
            vision_anchor="non-goals-not-robo-advisor",
        ),
        ac(
            "AC-advisor.guardrail.2",
            "Prompt-injection attempts (``is_prompt_injection``) and sensitive-data requests (``is_sensitive_request``) are detected and refused; sensitive numeric patterns are redacted from the user message and from the streamed response via ``StreamRedactor`` before persistence.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_safety_filters",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.13",
            "``StreamRedactor`` withholds emission of a chunk smaller than its configured tail size, accumulating it in an internal buffer instead of forwarding it immediately, so a sensitive pattern split across two small stream chunks cannot escape redaction.",
            "apps/backend/tests/infra/test_infra_edge_cases.py::test_stream_redactor_small_chunks",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.1",
            "A ``ChatSession`` is owned by exactly one user (``user_id`` foreign key, enforced at the ORM level); retrieving a session by id scopes the lookup to the requesting user.  Once a session is ARCHIVED (planned lifecycle addition) it is immutable — no further messages may be appended.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_get_or_create_session_with_existing_session",
            priority="P1",
            status="open",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.context.1",
            "Advisor answers are grounded only in the user's bounded read context (reconciliation readiness, report readiness, workflow status, portfolio positions, market data, category breakdown) — never in raw ledger writes or external data outside that context.  Each response carries ``citations`` and ``actions`` that surface the grounding sources.",
            "apps/backend/tests/ai/test_advisor_bounded_context.py::test_AC_advisor_context_1_context_is_exactly_the_bounded_read_set",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.cache.1",
            "Identical questions from the same user against the same financial context and model return the cached response (deterministic dedup by ``normalize_question(message) + sha256(context) + model_key``); the cache hit is recorded in the session and returned without an LLM round-trip.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_chat_stream_uses_cached_response",
            priority="P2",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.3",
            "A non-financial query (e.g. 'Tell me a joke about finance') is detected by ``is_non_financial``, verified alongside the other three guardrail predicates in the same assertion set.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_safety_filters",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.4",
            "Legitimate financial queries ('What are my expenses?', 'What is my account balance?', 'Show me my journal entries', 'How much did I spend on food?') pass all four guardrail predicates without being refused, so the guardrail does not over-block normal usage.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_safety_filters_negative_cases",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.5",
            "``ensure_disclaimer`` appends the localized disclaimer exactly once to a response that does not already contain it.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_ensure_disclaimer_appends_once",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.6",
            "``ensure_disclaimer`` is a no-op — it does not duplicate the disclaimer — when the response text already ends with it.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_ensure_disclaimer_respects_existing",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.7",
            "``StreamRedactor`` masks a sensitive numeric sequence even when it is split across multiple streamed chunks, replacing it with ``[REDACTED]`` in the concatenated output.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_redactor_masks_sensitive_sequences",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.8",
            "``StreamRedactor`` buffers a short tail chunk (shorter than ``tail_size``) without emitting it, then emits the buffered content on ``flush()``, so a sensitive sequence split at the very end of a stream is not leaked before it can be checked.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_redactor_flushes_tail",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.9",
            "``StreamRedactor.flush()`` returns an empty string when no data was buffered, rather than raising or returning a placeholder.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_redactor_flush_empty",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.10",
            "``build_refusal`` defaults to the non-financial-topic refusal message (mentioning 'finance') and still appends the disclaimer when called with an unrecognized refusal reason.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_build_refusal_defaults_to_non_financial",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.11",
            "``redact_sensitive`` masks a detected card-like numeric sequence in free text with ``[REDACTED]``, removing the original digits from the output.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_redact_sensitive",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.guardrail.12",
            "The bank-account PII detector skips date-like (e.g. '20240301') and zero-heavy (e.g. '90000000') numeric sequences, flagging only genuine account-like numbers (e.g. '812345678'), to avoid over-redacting ordinary numbers.",
            "apps/backend/tests/ai/test_pii_redaction.py::test_detect_pii_skips_date_like_and_zero_heavy_numbers",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.2",
            "``_get_or_create_session`` raises ``AIAdvisorError`` ('Chat session not found') when asked to resume a session id that does not exist.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_get_or_create_session_missing_raises",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.3",
            "``_load_history`` skips SYSTEM-role messages when reconstructing prior turns, returning only user/assistant messages to feed back into the model.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_load_history_skips_system_messages",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.4",
            "``_record_message`` sets the session's ``title`` from the first recorded message's content when the session has no title yet.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_record_message_sets_title",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.5",
            "``DELETE /api/chat/session/{id}`` marks the resolved ``ChatSession.status`` as DELETED and commits, rather than physically deleting the row.",
            "apps/backend/tests/ai/test_chat_router.py::test_delete_session_success",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.6",
            "``DELETE /api/chat/session/{id}`` returns 404 when the session id does not resolve for the requesting user.",
            "apps/backend/tests/ai/test_chat_router.py::test_delete_session_not_found",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.session.7",
            "``_record_message`` swallows an exception raised by ``db.refresh`` (logging a warning) rather than propagating it, so a refresh failure never surfaces as a fatal chat-turn error.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_record_message_refresh_exception_logs_warning",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.context.2",
            "``get_financial_context`` degrades gracefully when ``generate_balance_sheet``/``generate_income_statement``/``get_category_breakdown`` raise ``ReportError``, returning zeroed totals, ``top_expenses='N/A'``, and ``match_rate='0.0%'`` instead of propagating the error.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_get_financial_context_handles_report_errors",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.context.3",
            "``get_financial_context`` scopes monthly income/expenses, unmatched count, pending-review count, and match rate to the requesting user's own journal entries and reconciliation matches, excluding another user's transactions from the computation.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_get_financial_context_filters_by_user",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.context.4",
            "Prompt construction (``get_ai_advisor_prompt``) surfaces the structured ``advisor_context``/``advisor_suggestions`` facts verbatim and injects an explicit instruction that blocked report readiness is not trusted and that stale/unreviewed/unsupported/manual-trusted data must keep its stated limitation.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.cache.2",
            "``ResponseCache`` entries expire per their configured TTL: a ``ttl_seconds=0`` cache never returns a value it just set, while a ``ttl_seconds=60`` cache does.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_response_cache_ttl",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.cache.3",
            "``ResponseCache.prune()`` removes already-expired entries from the store so ``get()`` on a pruned key returns ``None``.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_response_cache_prune",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.1",
            "``_stream_openrouter`` falls back to the next configured fallback model when the primary model raises a retryable ``AIStreamError``, yielding chunks tagged with the model that actually served them.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_openrouter_falls_back",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.2",
            "``_stream_openrouter`` raises ``AIStreamError`` (mentioning the fallback model) when every configured model — primary and all fallbacks — fails.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_openrouter_raises_when_all_fail",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.3",
            "``chat_stream`` raises ``AIAdvisorError`` ('AI provider API key not configured') when no provider API key is configured, before attempting any model call.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_chat_stream_requires_api_key",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.4",
            "``_stream_and_store`` appends the disclaimer to the assembled response and records it in the ``ResponseCache`` under the request's cache key once the stream completes.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_and_store_records_response",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.5",
            "``_stream_and_store`` translates an underlying error from ``_stream_openrouter`` into ``AIAdvisorError`` (preserving the original message) rather than letting a raw exception escape the streaming generator.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_and_store_raises_on_stream_error",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.6",
            "On a cache miss, ``chat_stream`` returns a ``ChatStream`` with ``cached=False`` whose stream is backed by ``_stream_and_store``'s live pipeline rather than a cached string.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_chat_stream_success_path_uses_stream",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.7",
            "``_stream_openrouter`` tries a caller-supplied ``preferred_model`` before the primary/fallback list, so a per-request model override takes precedence.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_openrouter_with_preferred_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.8",
            "``_stream_openrouter`` converts a ``ValueError``/``TypeError`` raised inside ``_stream_model`` (a programming error, not a transient provider failure) into ``AIAdvisorError`` with an 'Internal error: <ExcType>' message, distinguishing it from retryable provider failures.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_openrouter_raises_on_programming_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.stream.9",
            "``_stream_model`` proxies chunks yielded by the underlying ``stream_ai_chat`` transport call unchanged, chunk-by-chunk.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_model_yields_chunks",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.textutil.1",
            "``normalize_question`` strips leading/trailing whitespace and lowercases the question text so equivalent phrasings produce the same cache key.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_normalize_question",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.textutil.3",
            "``AIAdvisorService._chunk_text`` splits a string into fixed-size pieces of the requested size, preserving all characters across chunks.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_chunk_text_splits_text",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.language.1",
            "``detect_language`` classifies Chinese-language input (e.g. '这个月花了多少钱') as 'zh'.",
            "apps/backend/tests/ai/test_chat_router.py::test_detect_language_chinese",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.language.2",
            "``detect_language`` classifies English-language input (e.g. 'What are my expenses?') as 'en'.",
            "apps/backend/tests/ai/test_chat_router.py::test_detect_language_english",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.language.3",
            "The chat-suggestions endpoint auto-detects Chinese from the caller's ``message`` text (when no explicit ``language`` is given) and returns Chinese-language suggestions.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_auto_detect_zh",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.language.4",
            "The chat-suggestions endpoint auto-detects English from the caller's ``message`` text and returns English-language suggestions.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_auto_detect_en",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.suggestions.1",
            "``GET /api/chat/suggestions?language=zh`` returns Chinese-language quick-question suggestions (first entry contains '支出'); a static localized-copy selection, not an LLM call.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_zh",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.suggestions.2",
            "``GET /api/chat/suggestions?language=en`` returns English-language quick-question suggestions (first entry contains 'What are my expenses'); a static localized-copy selection, not an LLM call.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_en",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.suggestions.3",
            "The chat-suggestions endpoint, when ``include_structured=True``, exposes the advisor's structured source-cited facts (``basis``, ``confidence_tier``, ``source_refs``, ``limitation``, ``next_action_href``) as ``structured_suggestions`` sourced from ``get_advisor_context``, without depending on parsing LLM prose.",
            "apps/backend/tests/ai/test_chat_router.py::test_AC21_3_1_chat_suggestions_include_structured_advisor_facts",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.api.1",
            "``POST /api/chat`` returns HTTP 503 with a 'temporarily unavailable' message when the underlying ``AIAdvisorError`` indicates the provider API key is unavailable.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_error_api_key_unavailable",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.api.2",
            "``POST /api/chat`` returns HTTP 404 when the underlying ``AIAdvisorError`` indicates the requested session was not found.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_error_session_not_found",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.api.3",
            "``POST /api/chat`` returns HTTP 400 when the underlying ``AIAdvisorError`` indicates an invalid/bad request.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_error_bad_request",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.api.4",
            "``POST /api/chat`` sets the ``X-Model-Name`` response header (listed in ``Access-Control-Expose-Headers``) to the model that actually served the response.",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_with_model_name_header",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.api.5",
            "``POST /api/chat`` omits the ``X-Model-Name`` header entirely when the stream result carries no model name (e.g. a guardrail-refused/cached-only response).",
            "apps/backend/tests/ai/test_chat_router.py::test_chat_without_model_name_header",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.envelope.1",
            "``ChatStreamEnvelope`` with only a ``session_id`` set builds a text/plain response exposing just ``X-Session-Id`` (no model/metadata headers), with ``Access-Control-Expose-Headers`` listing exactly that one header.",
            "apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_1_chat_envelope_minimal_headers",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.envelope.2",
            "``ChatStreamEnvelope`` with a model name and non-empty ``ChatResponseMetadata`` exposes ``X-Model-Name`` and a JSON ``X-Advisor-Metadata`` header, and lists all three headers in ``Access-Control-Expose-Headers`` in a fixed CORS order.",
            "apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_2_chat_envelope_includes_model_and_metadata_headers",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.envelope.3",
            "``ChatStreamEnvelope`` omits ``X-Advisor-Metadata`` (and excludes it from ``Access-Control-Expose-Headers``) when the attached ``ChatResponseMetadata`` is empty (not grounded, no citations/actions).",
            "apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_3_chat_envelope_omits_empty_advisor_metadata",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.envelope.4",
            "Constructing a ``ChatStreamEnvelope`` with advisor metadata that violates the ``ChatResponseMetadata`` schema (e.g. a non-boolean ``grounded``) raises a Pydantic ``ValidationError`` instead of silently accepting malformed metadata.",
            "apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_4_chat_envelope_rejects_invalid_advisor_metadata",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.envelope.5",
            "``chat_message`` builds its ``StreamingResponse`` from ``ChatStreamEnvelope.to_headers()`` — media type, ``X-Session-Id``, ``X-Model-Name``, and a dict-shaped advisor-metadata payload coerced into the validated ``X-Advisor-Metadata`` header — so the typed envelope governs the actual wire response without changing its bytes.",
            "apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.txn.1",
            "The advisor reads other domains (portfolio, reconciliation, reporting) only via their published interfaces, in a read-only transaction; it never writes into another domain's tables.  The write guardrail (AC-advisor.guardrail.1) is the runtime enforcement; this AC governs the structural boundary (once cross-domain packages publish their interfaces, the advisor's imports must use those, not internal service paths).",
            "tests/tooling/test_advisor_package.py::test_AC_advisor_txn_1_reads_only_published_interfaces",
            proof_kind="property",
        ),
        # ── group grounding: grounded chat answers with citations/next-action
        # chips (was EPIC-022 AC22.14.1/AC22.14.3, #1821 Wave A
        # pending-package move) ──
        ac(
            "AC-advisor.grounding.1",
            "POST /api/chat exposes structured grounding metadata for personal-data answers, including source citations with confidence tiers, without sending or returning raw account numbers or transaction-level PII.",
            "apps/backend/tests/ai/test_chat_router.py::test_AC22_14_1_chat_response_exposes_grounding_metadata_header",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-advisor.grounding.2",
            "A grounded chat answer that has pending reconciliation review context exposes a 'Review N' action deep-link to the review queue while preserving the assistant's read-only/no-write boundary.",
            "apps/backend/tests/ai/test_ai_advisor_service.py::test_AC22_14_3_chat_grounding_metadata_links_pending_review_without_write_actions",
            priority="P1",
            proof_kind="property",
        ),
        # NOTE: AC21.1.1 was evaluated for this move and REJECTED: its own
        # proving test (test_AC21_1_1_ai_advisor_is_application_layer_contract)
        # hard-asserts `registry_entries["AC21.1.1"]["epic_name"] ==
        # "application-ai-advisor"` — a package-scoped id's registry entry
        # gets `epic_name="pkg-advisor"` instead (see
        # generate_ac_registry.py's `_package_roadmap_acs`), so migrating
        # would require also editing this assertion, not a pure "move".
        # AC21.1.1 is left untouched as `horizontal` (#1821 Wave A).
        # ── group application-layer: the advisor is a read-only application
        # layer, not the source of record (was EPIC-021 AC21.1.2, #1821 Wave
        # A horizontal move) ──
        ac(
            "AC-advisor.application-layer.1",
            "Scale coverage and confidence work is explicitly routed to existing EPICs and issues instead of being re-owned by EPIC-021.",
            "tests/tooling/test_application_ai_advisor_epic021_contract.py::test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics",
            priority="P1",
            proof_kind="property",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ac(
            "AC-advisor.fe-chat.1",
            "Chat page renders advisor client within suspense boundary",
            "apps/frontend/src/__tests__/chatPage.test.tsx::AC16.16.3 renders advisor client",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.2",
            "Chat page client enforces disclaimer consent and passes initial prompt into chat panel",
            "apps/frontend/src/__tests__/ChatPageClient.test.tsx::AC16.19.5 AC16.20.2 shows consent modal when not accepted",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.3",
            "Chat page client renders primary navigation links and first-class conversational IA",
            "apps/frontend/src/__tests__/ChatPageClient.test.tsx::AC16.19.6 AC16.20.2 renders navigation links",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.4",
            "Chat panel sends streaming responses, loads suggestions/history, and clears session",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC16.20.5 loads suggestions/history and streams reply",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.5",
            "Handles missing stream reader",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC16.20.7 handles missing stream reader",
            priority="P1",
        ),
        ac(
            "AC-advisor.fe-chat.6",
            "ChatPanel renders modern conversational bubbles with avatar and right-aligned user bubble, avoiding full-width rectangular bars",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC-advisor.fe-chat.6 renders modern conversational bubbles with avatar",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.7",
            "ChatPanel formats structured markdown tables, lists, and bold text for assistant responses",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC-advisor.fe-chat.7 formats structured markdown tables and bold text",
            priority="P2",
        ),
        ac(
            "AC-advisor.fe-chat.8",
            "ChatPanel input area provides auto-growing textarea, circular send button, and resolves persistent loading indicators",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC-advisor.fe-chat.8 input area supports auto-grow and circular send",
            priority="P2",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ac(
            "AC-advisor.fe-ia-chat.1",
            "`ChatPanel` renders assistant-answer citations as safe internal links and shows pending-action chips without parsing LLM prose",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC22.14.2 AC22.14.3 renders grounded answer citations and pending action chips",
            priority="P1",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ac(
            "AC-advisor.fe-remainder-chat.1",
            "`/chat` is a simple AI utility page with model selector, active conversation, and session-list drawer; it is not labeled AI Settings",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC19.8.6 shows chat sessions inside the AI page without workflow ownership",
            priority="P1",
        ),
        ac(
            "AC-advisor.fe-remainder-chat.2",
            "Advisor Brief renders blocked, ready, review-required, and stale-market-data cards with source basis, limitation, and safe internal action links",
            "apps/frontend/src/__tests__/advisorBrief.test.tsx::AC21.3.2 test_AC21_3_2_advisor_brief_renders_structured_cards_and_safe_routes",
        ),
        ac(
            "AC-advisor.fe-remainder-chat.3",
            "Chat and dashboard surfaces expose contextual Ask AI links that seed a scoped prompt without losing existing chat behavior",
            "apps/frontend/src/__tests__/chatPanelComponent.test.tsx::AC21.3.3 test_AC21_3_3_chat_panel_renders_contextual_advisor_brief",
        ),
        ac(
            "AC-advisor.fe-remainder-chat.4",
            "Advisor Brief keeps desktop and mobile layouts free of horizontal overflow",
            "apps/frontend/playwright/advisor-brief.spec.ts::${scenario.name} advisor-brief desktop and mobile layouts avoid horizontal overflow",
            priority="P1",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="ai_advisor_policy",
            owner="common/advisor/readme.md",
            description=(
                "AI advisor application-layer contract, prompt policy, context scope, and "
                "safety controls."
            ),
            cross_refs=[
                "common/llm/ai.md",
                "common/reporting/reporting.md",
                "common/workflow/workflow-events.md",
                "apps/backend/src/extraction/base/source_capability.py",
                "common/pricing/market_data.md",
                "docs/project/EPIC-021.application-ai-advisor.md",
            ],
            family="ai",
            kind="concept",
        ),
    ],
)
