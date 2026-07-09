"""The ``advisor`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against.
In this PR1 slice ``implementations["be"]`` is ``None`` (the code still lives
at ``apps/backend/src/services/ai_advisor``), so the gate skips the
``interface == __all__`` check; PR2 moves the code to
``apps/backend/src/advisor``, sets ``implementations["be"]`` accordingly, and
the check then applies. Every ``invariants[].test`` and ``roadmap[].test``
must resolve to a real test function; ``depends_on`` must not introduce a
forbidden upward/sideways edge.

## What this package is

The application-layer AI financial advisor (EPIC-006 / EPIC-021): a
read-only conversational interface over the user's financial state.  The
advisor **never writes a ledger number** — it only reads from the user's
bounded context (reconciliation readiness, reporting summaries, portfolio
positions) and streams a grounded, cited, disclaimer-tagged response.

## Boundaries (confirmed at cutover, 2026-07-06)

* **read-only guardrail** — every write/mutation request (`is_write_request`),
  every prompt-injection attempt (`is_prompt_injection`), and every
  sensitive-data request (`is_sensitive_request`) is refused before any LLM
  call is made.  The guardrail is also applied on the streaming path via
  `StreamRedactor`.  This is the package's non-negotiable invariant.
* **bounded context** — the advisor reads reconciliation/reporting/portfolio
  data as part of the same read-only request (currently the same
  `AsyncSession` as the chat-message insert — see ``AC-advisor.txn.1``,
  still ``open``: the target is reading via each package's *published*
  interface once reconciliation/reporting/portfolio ship contracts, never a
  cross-domain FK).  It never touches the ledger write side.
* **LLM via ``llm``** — all provider calls go through the ``llm`` package
  (`SceneBinding` / `CassetteStore`); the advisor owns no raw HTTP surface.
* **session ownership** — a `ChatSession` is owned by exactly one user;
  once a session is closed it is immutable (the ARCHIVED lifecycle is a
  planned addition — `AC-advisor.session.1`).

## Cross-domain read edges (added to ``depends_on`` once those packages ship)

The advisor currently reads from services that will become:
``portfolio``, ``reconciliation``, ``reporting``, ``pricing`` (market data).
These are *read-only* edges; the advisor never writes into them.  They will
be added to ``depends_on`` when their package contracts are registered.

## God-file → phase split (PR2 scope)

``apps/backend/src/services/ai_advisor/service.py`` (~860 lines) will be
split into ``phases/{context_aggregation,prompt_construction,response_streaming}.py``
and ``_guardrails.py`` will remain separate.  Until then the units are
declared *taxonomy-only* (``module=None``): the governance gate skips
placement checks for units without a module path, per the package model.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
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
    # infra: llm (scene binding + cassette), observability (logging), config
    # (settings).  Cross-domain read edges (portfolio, reconciliation,
    # reporting, pricing) are added once those packages ship contracts.
    depends_on=["llm", "observability", "config"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: aggregate root + entity + value language ──
        # These live in the ORM models today (src/models/chat.py); they will
        # move to base/ when the physical base/extension split happens in PR2.
        # Declared taxonomy-only (module=None) so the gate skips placement.
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
        # adapter in extension/.  Currently raw AsyncSession; port/adapter
        # split is PR2 scope.  Declared taxonomy-only until then.
        Unit(name="ChatSessionRepository", kind=Kind.REPOSITORY),
        # ── data: read-model projections ──
        # chat history view (list of sessions + messages for the UI)
        Unit(name="ChatHistoryView", kind=Kind.PROJECTION),
    ],
    # BE implementation target path.  The code is currently in
    # ``src/services/ai_advisor/``; it moves to ``src/advisor/`` in PR2.
    # ``None`` tells the gate to skip interface == __all__ checks for now.
    implementations={"be": None, "fe": None},
    # Published language: empty until the code lands at the target path and
    # src/advisor/__init__.py declares __all__.  Filled in PR2.
    interface=[],
    events=[],
    # Structural invariants: registered once the base/extension/data split is
    # done and the tooling tests exist (PR2 scope).
    invariants=[],
    # ── Roadmap: package-model AC registry ──
    # ACs migrated from EPIC-006 / EPIC-021 per Decision A (standard-
    # preserving move; the EPIC table rows are removed in a follow-up).
    # Original EPIC AC ids are kept as inline comments; existing test
    # functions keep their AC6_*/AC21_* names — the ``test=`` reference is
    # the resolvable anchor, not the function name.
    roadmap=[
        ACRecord(
            id="AC-advisor.guardrail.1",
            statement=(
                "A write/mutation request (create/post/delete/void/modify a "
                "journal or ledger entry) is detected by ``is_write_request`` "
                "and refused before any LLM call; the advisor never writes a "
                "ledger number."
            ),
            # was AC6.1.1 (partial) + AC6.7.7
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_chat_stream_refusal_branches"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.2",
            statement=(
                "Prompt-injection attempts (``is_prompt_injection``) and "
                "sensitive-data requests (``is_sensitive_request``) are "
                "detected and refused; sensitive numeric patterns are redacted "
                "from the user message and from the streamed response via "
                "``StreamRedactor`` before persistence."
            ),
            # was AC6.1.1 + AC21.2.3
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py::test_safety_filters"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.13",
            statement=(
                "``StreamRedactor`` withholds emission of a chunk smaller than "
                "its configured tail size, accumulating it in an internal "
                "buffer instead of forwarding it immediately, so a sensitive "
                "pattern split across two small stream chunks cannot escape "
                "redaction."
            ),
            # was AC2.12.5
            test=(
                "apps/backend/tests/infra/test_infra_edge_cases.py"
                "::test_stream_redactor_small_chunks"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.1",
            statement=(
                "A ``ChatSession`` is owned by exactly one user (``user_id`` "
                "foreign key, enforced at the ORM level); retrieving a session "
                "by id scopes the lookup to the requesting user.  Once a "
                "session is ARCHIVED (lifecycle addition, PR2 scope) it is "
                "immutable — no further messages may be appended."
            ),
            # was AC6.4.1 (user ownership portion); ARCHIVED state is PR2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_get_or_create_session_with_existing_session"
            ),
            priority="P1",
            # "open" because the ARCHIVED immutability invariant is not yet
            # implemented (ChatSessionStatus has ACTIVE/DELETED, not ARCHIVED).
            status="open",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.context.1",
            statement=(
                "Advisor answers are grounded only in the user's bounded read "
                "context (reconciliation readiness, report readiness, "
                "workflow status, portfolio positions, market data, category "
                "breakdown) — never in raw ledger writes or external data "
                "outside that context.  Each response carries ``citations`` "
                "and ``actions`` that surface the grounding sources."
            ),
            # was AC21.2.1
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_AC21_2_1_advisor_context_includes_readiness_trust_workflow_and_suggestions"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.cache.1",
            statement=(
                "Identical questions from the same user against the same "
                "financial context and model return the cached response "
                "(deterministic dedup by ``normalize_question(message) + "
                "sha256(context) + model_key``); the cache hit is recorded "
                "in the session and returned without an LLM round-trip."
            ),
            # was AC6.6.3
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_chat_stream_uses_cached_response"
            ),
            priority="P2",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.3",
            statement=(
                "A non-financial query (e.g. 'Tell me a joke about finance') is "
                "detected by ``is_non_financial``, verified alongside the other "
                "three guardrail predicates in the same assertion set."
            ),
            # was AC6.1.4
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_safety_filters",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.4",
            statement=(
                "Legitimate financial queries ('What are my expenses?', 'What "
                "is my account balance?', 'Show me my journal entries', 'How "
                "much did I spend on food?') pass all four guardrail "
                "predicates without being refused, so the guardrail does not "
                "over-block normal usage."
            ),
            # was AC6.1.5
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_safety_filters_negative_cases"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.5",
            statement=(
                "``ensure_disclaimer`` appends the localized disclaimer "
                "exactly once to a response that does not already contain it."
            ),
            # was AC6.3.1 (+ dup AC6.12.3)
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_ensure_disclaimer_appends_once"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.6",
            statement=(
                "``ensure_disclaimer`` is a no-op — it does not duplicate the "
                "disclaimer — when the response text already ends with it."
            ),
            # was AC6.3.2 (+ dup AC6.12.3)
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_ensure_disclaimer_respects_existing"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.7",
            statement=(
                "``StreamRedactor`` masks a sensitive numeric sequence even "
                "when it is split across multiple streamed chunks, replacing "
                "it with ``[REDACTED]`` in the concatenated output."
            ),
            # was AC6.7.4
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_redactor_masks_sensitive_sequences"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.8",
            statement=(
                "``StreamRedactor`` buffers a short tail chunk (shorter than "
                "``tail_size``) without emitting it, then emits the buffered "
                "content on ``flush()``, so a sensitive sequence split at the "
                "very end of a stream is not leaked before it can be checked."
            ),
            # was AC6.7.5
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_redactor_flushes_tail"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.9",
            statement=(
                "``StreamRedactor.flush()`` returns an empty string when no "
                "data was buffered, rather than raising or returning a "
                "placeholder."
            ),
            # was AC6.7.6
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_redactor_flush_empty"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.10",
            statement=(
                "``build_refusal`` defaults to the non-financial-topic "
                "refusal message (mentioning 'finance') and still appends "
                "the disclaimer when called with an unrecognized refusal "
                "reason."
            ),
            # was AC6.8.3
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_build_refusal_defaults_to_non_financial"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.11",
            statement=(
                "``redact_sensitive`` masks a detected card-like numeric "
                "sequence in free text with ``[REDACTED]``, removing the "
                "original digits from the output."
            ),
            # was AC6.10.3
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_redact_sensitive",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.guardrail.12",
            statement=(
                "The bank-account PII detector skips date-like (e.g. "
                "'20240301') and zero-heavy (e.g. '90000000') numeric "
                "sequences, flagging only genuine account-like numbers (e.g. "
                "'812345678'), to avoid over-redacting ordinary numbers."
            ),
            # was AC6.13.6
            test=(
                "apps/backend/tests/ai/test_pii_redaction.py"
                "::test_detect_pii_skips_date_like_and_zero_heavy_numbers"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.2",
            statement=(
                "``_get_or_create_session`` raises ``AIAdvisorError`` ('Chat "
                "session not found') when asked to resume a session id that "
                "does not exist."
            ),
            # was AC6.4.2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_get_or_create_session_missing_raises"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.3",
            statement=(
                "``_load_history`` skips SYSTEM-role messages when "
                "reconstructing prior turns, returning only user/assistant "
                "messages to feed back into the model."
            ),
            # was AC6.4.3
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_load_history_skips_system_messages"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.4",
            statement=(
                "``_record_message`` sets the session's ``title`` from the "
                "first recorded message's content when the session has no "
                "title yet."
            ),
            # was AC6.4.4
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_record_message_sets_title"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.5",
            statement=(
                "``DELETE /api/chat/session/{id}`` marks the resolved "
                "``ChatSession.status`` as DELETED and commits, rather than "
                "physically deleting the row."
            ),
            # was AC6.4.5
            test="apps/backend/tests/ai/test_chat_router.py::test_delete_session_success",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.6",
            statement=(
                "``DELETE /api/chat/session/{id}`` returns 404 when the "
                "session id does not resolve for the requesting user."
            ),
            # was AC6.4.6
            test="apps/backend/tests/ai/test_chat_router.py::test_delete_session_not_found",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.session.7",
            statement=(
                "``_record_message`` swallows an exception raised by "
                "``db.refresh`` (logging a warning) rather than propagating "
                "it, so a refresh failure never surfaces as a fatal "
                "chat-turn error."
            ),
            # was AC6.13.1
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_record_message_refresh_exception_logs_warning"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.context.2",
            statement=(
                "``get_financial_context`` degrades gracefully when "
                "``generate_balance_sheet``/``generate_income_statement``/"
                "``get_category_breakdown`` raise ``ReportError``, returning "
                "zeroed totals, ``top_expenses='N/A'``, and "
                "``match_rate='0.0%'`` instead of propagating the error."
            ),
            # was AC6.8.1
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_get_financial_context_handles_report_errors"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.context.3",
            statement=(
                "``get_financial_context`` scopes monthly income/expenses, "
                "unmatched count, pending-review count, and match rate to "
                "the requesting user's own journal entries and "
                "reconciliation matches, excluding another user's "
                "transactions from the computation."
            ),
            # was AC6.8.2 (+ dup AC6.12.2, AC6.12.6)
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_get_financial_context_filters_by_user"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.context.4",
            statement=(
                "Prompt construction (``get_ai_advisor_prompt``) surfaces "
                "the structured ``advisor_context``/``advisor_suggestions`` "
                "facts verbatim and injects an explicit instruction that "
                "blocked report readiness is not trusted and that "
                "stale/unreviewed/unsupported/manual-trusted data must keep "
                "its stated limitation."
            ),
            # was AC21.2.2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.cache.2",
            statement=(
                "``ResponseCache`` entries expire per their configured TTL: "
                "a ``ttl_seconds=0`` cache never returns a value it just "
                "set, while a ``ttl_seconds=60`` cache does."
            ),
            # was AC6.6.1
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_response_cache_ttl",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.cache.3",
            statement=(
                "``ResponseCache.prune()`` removes already-expired entries "
                "from the store so ``get()`` on a pruned key returns "
                "``None``."
            ),
            # was AC6.6.2
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_response_cache_prune",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.1",
            statement=(
                "``_stream_openrouter`` falls back to the next configured "
                "fallback model when the primary model raises a retryable "
                "``AIStreamError``, yielding chunks tagged with the model "
                "that actually served them."
            ),
            # was AC6.7.1 (+ dup AC6.12.5)
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_openrouter_falls_back"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.2",
            statement=(
                "``_stream_openrouter`` raises ``AIStreamError`` (mentioning "
                "the fallback model) when every configured model — primary "
                "and all fallbacks — fails."
            ),
            # was AC6.7.2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_openrouter_raises_when_all_fail"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.3",
            statement=(
                "``chat_stream`` raises ``AIAdvisorError`` ('AI provider API "
                "key not configured') when no provider API key is "
                "configured, before attempting any model call."
            ),
            # was AC6.7.3
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_chat_stream_requires_api_key",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.4",
            statement=(
                "``_stream_and_store`` appends the disclaimer to the "
                "assembled response and records it in the ``ResponseCache`` "
                "under the request's cache key once the stream completes."
            ),
            # was AC6.8.4
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_and_store_records_response"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.5",
            statement=(
                "``_stream_and_store`` translates an underlying error from "
                "``_stream_openrouter`` into ``AIAdvisorError`` (preserving "
                "the original message) rather than letting a raw exception "
                "escape the streaming generator."
            ),
            # was AC6.9.1
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_and_store_raises_on_stream_error"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.6",
            statement=(
                "On a cache miss, ``chat_stream`` returns a ``ChatStream`` "
                "with ``cached=False`` whose stream is backed by "
                "``_stream_and_store``'s live pipeline rather than a cached "
                "string."
            ),
            # was AC6.9.2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_chat_stream_success_path_uses_stream"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.7",
            statement=(
                "``_stream_openrouter`` tries a caller-supplied "
                "``preferred_model`` before the primary/fallback list, so a "
                "per-request model override takes precedence."
            ),
            # was AC6.13.2
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_openrouter_with_preferred_model"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.8",
            statement=(
                "``_stream_openrouter`` converts a ``ValueError``/"
                "``TypeError`` raised inside ``_stream_model`` (a "
                "programming error, not a transient provider failure) into "
                "``AIAdvisorError`` with an 'Internal error: <ExcType>' "
                "message, distinguishing it from retryable provider "
                "failures."
            ),
            # was AC6.13.3
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_stream_openrouter_raises_on_programming_error"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.stream.9",
            statement=(
                "``_stream_model`` proxies chunks yielded by the underlying "
                "``stream_ai_chat`` transport call unchanged, chunk-by-chunk."
            ),
            # was AC6.13.4
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_stream_model_yields_chunks",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.textutil.1",
            statement=(
                "``normalize_question`` strips leading/trailing whitespace "
                "and lowercases the question text so equivalent phrasings "
                "produce the same cache key."
            ),
            # was AC6.10.1
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_normalize_question",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.textutil.2",
            statement=(
                "``estimate_tokens`` approximates a token count from "
                "character length (roughly 4 characters per token) and "
                "never returns less than 1, even for an empty string."
            ),
            # was AC6.10.2
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_estimate_tokens",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.textutil.3",
            statement=(
                "``AIAdvisorService._chunk_text`` splits a string into "
                "fixed-size pieces of the requested size, preserving all "
                "characters across chunks."
            ),
            # was AC6.10.4
            test="apps/backend/tests/ai/test_ai_advisor_service.py::test_chunk_text_splits_text",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.language.1",
            statement=(
                "``detect_language`` classifies Chinese-language input (e.g. "
                "'这个月花了多少钱') as 'zh'."
            ),
            # was AC6.2.1 (+ dup AC6.12.4)
            test="apps/backend/tests/ai/test_chat_router.py::test_detect_language_chinese",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.language.2",
            statement=(
                "``detect_language`` classifies English-language input (e.g. "
                "'What are my expenses?') as 'en'."
            ),
            # was AC6.2.2 (+ dup AC6.12.4)
            test="apps/backend/tests/ai/test_chat_router.py::test_detect_language_english",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.language.3",
            statement=(
                "The chat-suggestions endpoint auto-detects Chinese from "
                "the caller's ``message`` text (when no explicit "
                "``language`` is given) and returns Chinese-language "
                "suggestions."
            ),
            # was AC6.2.5
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_auto_detect_zh",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.language.4",
            statement=(
                "The chat-suggestions endpoint auto-detects English from "
                "the caller's ``message`` text and returns English-language "
                "suggestions."
            ),
            # was AC6.2.6
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_auto_detect_en",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.suggestions.1",
            statement=(
                "``GET /api/chat/suggestions?language=zh`` returns "
                "Chinese-language quick-question suggestions (first entry "
                "contains '支出'); a static localized-copy selection, not an "
                "LLM call."
            ),
            # was AC6.2.3 (+ dup AC6.5.2)
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_zh",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.suggestions.2",
            statement=(
                "``GET /api/chat/suggestions?language=en`` returns "
                "English-language quick-question suggestions (first entry "
                "contains 'What are my expenses'); a static localized-copy "
                "selection, not an LLM call."
            ),
            # was AC6.2.4 (+ dup AC6.5.1)
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_suggestions_en",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.suggestions.3",
            statement=(
                "The chat-suggestions endpoint, when "
                "``include_structured=True``, exposes the advisor's "
                "structured source-cited facts (``basis``, "
                "``confidence_tier``, ``source_refs``, ``limitation``, "
                "``next_action_href``) as ``structured_suggestions`` "
                "sourced from ``get_advisor_context``, without depending on "
                "parsing LLM prose."
            ),
            # was AC21.3.1
            test=(
                "apps/backend/tests/ai/test_chat_router.py"
                "::test_AC21_3_1_chat_suggestions_include_structured_advisor_facts"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.api.1",
            statement=(
                "``POST /api/chat`` returns HTTP 503 with a 'temporarily "
                "unavailable' message when the underlying ``AIAdvisorError`` "
                "indicates the provider API key is unavailable."
            ),
            # was AC6.5.3 (+ dup AC6.12.5)
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_error_api_key_unavailable",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.api.2",
            statement=(
                "``POST /api/chat`` returns HTTP 404 when the underlying "
                "``AIAdvisorError`` indicates the requested session was not "
                "found."
            ),
            # was AC6.5.4
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_error_session_not_found",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.api.3",
            statement=(
                "``POST /api/chat`` returns HTTP 400 when the underlying "
                "``AIAdvisorError`` indicates an invalid/bad request."
            ),
            # was AC6.5.5
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_error_bad_request",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.api.4",
            statement=(
                "``POST /api/chat`` sets the ``X-Model-Name`` response "
                "header (listed in ``Access-Control-Expose-Headers``) to "
                "the model that actually served the response."
            ),
            # was AC6.5.6
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_with_model_name_header",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.api.5",
            statement=(
                "``POST /api/chat`` omits the ``X-Model-Name`` header "
                "entirely when the stream result carries no model name "
                "(e.g. a guardrail-refused/cached-only response)."
            ),
            # was AC6.5.7
            test="apps/backend/tests/ai/test_chat_router.py::test_chat_without_model_name_header",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.envelope.1",
            statement=(
                "``ChatStreamEnvelope`` with only a ``session_id`` set "
                "builds a text/plain response exposing just "
                "``X-Session-Id`` (no model/metadata headers), with "
                "``Access-Control-Expose-Headers`` listing exactly that one "
                "header."
            ),
            # was AC6.33.1
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_1_chat_envelope_minimal_headers"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.envelope.2",
            statement=(
                "``ChatStreamEnvelope`` with a model name and non-empty "
                "``ChatResponseMetadata`` exposes ``X-Model-Name`` and a "
                "JSON ``X-Advisor-Metadata`` header, and lists all three "
                "headers in ``Access-Control-Expose-Headers`` in a fixed "
                "CORS order."
            ),
            # was AC6.33.2
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_2_chat_envelope_includes_model_and_metadata_headers"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.envelope.3",
            statement=(
                "``ChatStreamEnvelope`` omits ``X-Advisor-Metadata`` (and "
                "excludes it from ``Access-Control-Expose-Headers``) when "
                "the attached ``ChatResponseMetadata`` is empty (not "
                "grounded, no citations/actions)."
            ),
            # was AC6.33.3
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_3_chat_envelope_omits_empty_advisor_metadata"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.envelope.4",
            statement=(
                "Constructing a ``ChatStreamEnvelope`` with advisor "
                "metadata that violates the ``ChatResponseMetadata`` schema "
                "(e.g. a non-boolean ``grounded``) raises a Pydantic "
                "``ValidationError`` instead of silently accepting "
                "malformed metadata."
            ),
            # was AC6.33.4
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_4_chat_envelope_rejects_invalid_advisor_metadata"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.envelope.5",
            statement=(
                "``chat_message`` builds its ``StreamingResponse`` from "
                "``ChatStreamEnvelope.to_headers()`` — media type, "
                "``X-Session-Id``, ``X-Model-Name``, and a dict-shaped "
                "advisor-metadata payload coerced into the validated "
                "``X-Advisor-Metadata`` header — so the typed envelope "
                "governs the actual wire response without changing its "
                "bytes."
            ),
            # was AC6.33.7
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-advisor.txn.1",
            statement=(
                "The advisor reads other domains (portfolio, reconciliation, "
                "reporting) only via their published interfaces, in a "
                "read-only transaction; it never writes into another domain's "
                "tables.  The write guardrail (AC-advisor.guardrail.1) is the "
                "runtime enforcement; this AC governs the structural boundary "
                "(once cross-domain packages publish their interfaces, the "
                "advisor's imports must use those, not internal service paths)."
            ),
            # was (new): reinforces guardrail.1 + context.1 at the boundary level
            test=(
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_chat_stream_refusal_branches"
            ),
            priority="P0",
            # "open" because the structural read-via-interface constraint is
            # not yet enforced (reconciliation/reporting/portfolio contracts
            # are not yet registered; the advisor still imports from
            # src.services.*).  The runtime write-refusal is done.
            status="open",
            proof_kind="property",
        ),
    ],
)
