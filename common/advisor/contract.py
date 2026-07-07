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
                "apps/backend/tests/ai/test_ai_advisor_service.py"
                "::test_safety_filters"
            ),
            priority="P0",
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
