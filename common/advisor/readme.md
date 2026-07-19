# `advisor` — application-layer AI financial advisor

> The spec + review surface for the ``advisor`` package. Machine contract:
> [`contract.py`](./contract.py).
>
> This `common/advisor/` directory is the **spec surface**; the conforming
> implementation lives at
> [`apps/backend/src/advisor`](../../apps/backend/src/advisor)
> (`contract.implementations["be"]`), physically moved there by #1671 Wave B
> (absorbing `prompts/ai_advisor.py` and `models/chat.py` → `orm/chat.py`).
> The annualized-income schedule is reporting-owned (#567).

## Why

Users need to answer questions like *"Why is my net worth down this month?"*
or *"What do my reconciliation blockers mean for my tax submission?"*
without manually cross-referencing balance sheets, reconciliation queues,
and portfolio positions.  `advisor` is the read-only conversational layer
that does this aggregation, grounding every answer in deterministic
application facts (no hallucinated numbers) and citing the sources it used.

## The non-negotiable invariant

> **The advisor never writes a ledger number.**

Every write/mutation request is refused before any LLM call is made
(`is_write_request` → `build_refusal("write", …)`).  Prompt-injection
attempts and sensitive-data requests are also refused (`is_prompt_injection`,
`is_sensitive_request`).  Sensitive numeric patterns (account numbers, card
numbers) are redacted from the user message before it reaches the provider
and from the streamed response via `StreamRedactor` before persistence.  This
invariant is P0 across all delivery tiers.

## Ubiquitous language

- **`ChatSession`** — the aggregate root.  Owned by exactly one user
  (`user_id`); groups all messages for one conversation thread.  Lifecycle:
  `ACTIVE` (default) → `ARCHIVED` (planned, immutable once closed).
- **`ChatMessage`** — an immutable record of one turn: role (`USER` /
  `ASSISTANT`), content, and optional token counts + model name.  Owned by
  its `ChatSession`.
- **`ChatSessionStatus`** / **`ChatMessageRole`** — the lifecycle and role
  enumerations for sessions and messages.
- **`ChatStream`** — the streaming result: a `(session_id, async_iterator,
  model_name, cached, metadata)` value that callers consume chunk-by-chunk.
- **`ChatResponseMetadata`** — the grounding envelope attached to each
  streamed answer: `citations` (source → href → confidence tier) and
  `actions` (safe next-step chips).
- **`AdvisorSuggestion`** — a source-cited, confidence-tiered nudge
  ("Report readiness is blocked with 2 blockers — review them before
  trusting the balance sheet").
- **`ChatCitation`** — one grounding source reference: label, source-ref
  key, confidence tier, and a safe href.
- **`AIAdvisorService`** — the primary domain service.  Orchestrates:
  guardrail evaluation → context aggregation → prompt construction →
  cache lookup → LLM stream → redaction → persistence.
- **`AdvisorGuardrails`** — the guardrail suite: injection / write /
  sensitive / non-financial detection functions + `StreamRedactor`.
- **`ResponseCache`** — in-process TTL cache keyed by
  `user_id + language + normalize_question(msg) + sha256(context) + model`.
  A cache hit avoids an LLM round-trip and is recorded in the session as a
  `model_name="cache"` message.
- **`AdvisorSceneBinding`** — resolves the per-user `advisor.chat`
  `SceneBinding` from the `llm` config source (DB providers first, env
  fallback).  Best-effort: a broken per-user config falls back to the env
  model list rather than breaking the chat session.
- **LLM consumption** — bound advisor calls use `llm.LLMClient` with
  `Scene.ADVISOR_CHAT`; token estimation and worst-confidence ranking are
  consumed from their `llm` and `ledger` owners, never redefined here.
- **`ChatSessionRepository`** — the deferred repository port (base) + SQL
  adapter (extension); the current implementation still uses raw
  `AsyncSession`.
- **`ChatHistoryView`** — the read-model projection: paginated chat history
  for the UI (list of sessions + messages, no write state).

## Read context (bounded, read-only)

## Bounded-context decision

`advisor` is an application-layer read model and explanation boundary, not a
domain owner. It may aggregate stable projections from domain packages and ask
`llm` to phrase grounded facts, but it cannot write their state or redefine
their policy. Its complete, consumer-owned relationship classification lives in
[`contract.py`](./contract.py); the `platform` relationship is explicitly
composition support, while domain reads are published language or projections.

The advisor aggregates context from:

| Source | What it reads | How the advisor reads it |
|--------|--------------|---------------------------|
| `report_readiness` | Readiness state + blockers | `src.reporting` published root (`get_personal_report_package_readiness`, #1666) |
| `reporting` | Balance sheet, income statement, category breakdown | `src.reporting` published root (`generate_balance_sheet`/`generate_income_statement`/`get_category_breakdown`, #1666) |
| `reconciliation` | Pending review count, reconciliation stats | `src.reconciliation` published root (`get_reconciliation_stats`) |
| `portfolio` | Positions, unrealised P&L, active symbols | `src.portfolio` published root (`PortfolioService`, `active_stock_symbols`) |
| `market_data` | Scope status, prices | `src.pricing` published root (`get_market_data_status`); the FX-pair composer is an `extension/app_reads.py` port, now wired to `src.composition` (#1610 re-homed it from `services/market_data_scheduler.py`) |
| `workflow_events` | Action-required counts | `src.platform` published root (`get_workflow_status`, #1703) |

The one remaining `app_reads` port (the FX-pair composer) is wired by the
composition root (`src/main.py`) — the same inversion #1676 used for
platform's readiness port. It stays a port rather than collapsing into a
direct import even after #1610: `observed_fx_pairs` composes ledger +
portfolio + extraction reads (#1641), which `advisor` must not import
directly (same-layer L3 peers) — the composition root is the only place
allowed to see all three.

All reads are in the same `AsyncSession` transaction as the chat message
insert (the advisor's own transaction — `AC-advisor.txn.1`, proven by
`tests/tooling/test_advisor_package.py`).  The advisor never holds a
reference to another domain's write objects.

## Layers (physical, since #1671 Wave B)

| Layer | What lives here |
|-------|-----------------|
| `base/` | `prompt.py` (template + disclaimers), `constants.py` (patterns, safe hrefs), `guardrails.py` (pure predicates + `StreamRedactor`) |
| `extension/` | `service.py` (`AIAdvisorService`, `ChatStream`), `cache.py` (`ResponseCache`), `app_reads.py` (remainder-read ports) |
| `orm/` | `chat.py` (`ChatSession` AR, `ChatMessage` entity, status/role enums — schema-neutral move from `src/models/chat.py`) |
| `data/` | reserved for the `ChatHistoryView` projection (declared taxonomy-only) |

The ARCHIVED session lifecycle is scheduled by `AC-advisor.session.1`. A
service phase split, the `ChatSessionRepository` port/adapter split, and the
`ChatHistoryView` projection remain deferred design options, not scheduled
work; adopting one requires a GitHub issue and a tested roadmap AC first.

## Usage

```python
from src.advisor import AIAdvisorService, ChatStream

service = AIAdvisorService()
chat: ChatStream = await service.chat_stream(db, user_id=user.id, message="Why is my net worth down?")

async for chunk in chat.stream:
    yield chunk  # SSE chunk to the client
```

The `metadata` field on `ChatStream` carries the grounding envelope
(`ChatResponseMetadata`) populated before the stream begins, so the UI can
render citations and action chips immediately.

## Guardrails

```python
from src.advisor import is_write_request, is_prompt_injection, is_sensitive_request

# These are checked inside chat_stream before any LLM call:
is_write_request("Create a journal entry for rent")  # True → refused
is_prompt_injection("Ignore previous instructions")  # True → refused
is_sensitive_request("My account number is 1234567890")  # True → refused
```

## Cache

Cache key: `f"{user_id}:{language}:{normalize_question(message)}:{sha256(context)}:{model_key}"`.
TTL: 3600 s (1 hour).  A cache hit skips the LLM call and records the
cached response in the session with `model_name="cache"`.

## Governance

The package's ACs (`AC-advisor.guardrail.*`, `AC-advisor.session.*`,
`AC-advisor.context.*`, `AC-advisor.cache.*`, `AC-advisor.txn.*`) live in
[`contract.py`](./contract.py)'s `roadmap` and are sourced **directly** from
there into the AC registry (no EPIC mirror); its invariants pin to the tests
that prove them.
`tools/check_package_contract.py` validates the implementation against this
contract (interface == `__all__`, every test reference resolves, no upward
import edge).

## Application-Layer Advisor Contract (EPIC-021)

*(Internalized from `common/llm/ai.md`, migration closeout wave 3, #1664 —
this is now the single owner; do not re-add a separate SSOT copy.)*

EPIC-021 upgrades the advisor from generic chat to product guidance: the
backend assembles deterministic application facts first, and the LLM may
only explain, prioritize, and phrase those facts. Application context can
include report package readiness/snapshot/export status and traceability
gaps (from `reporting`), upload-to-report workflow events and blocked steps
(from `platform`'s workflow events), source-class trust/proof-level/review
requirements (from the source coverage matrix), portfolio holdings and
valuation facts (from `portfolio`/`reporting`), market-data freshness (from
`pricing`), and cash-flow observations from posted/reconciled ledger
summaries.

**Advisor output contract** for a structured suggestion:

- `basis` — the deterministic application fact or user question that
  triggered the suggestion.
- `source_refs` — internal report/workflow/source/portfolio/market-data
  references that support the suggestion.
- `confidence_tier` — `deterministic`, `review_required`, `stale`,
  `unsupported`, or `blocked`.
- `limitation` — what the user should not rely on yet.
- `next_action_href` — a safe internal route for the next in-product action.

`AIAdvisorService.get_advisor_context()` is the deterministic advisor-fact
assembly boundary: it composes legacy financial-summary fields with report
package readiness, source trust, workflow status, market-data freshness,
portfolio summary, cash-flow observations, and `AdvisorSuggestion` objects
before prompt construction. The prompt receives the serialized structured
facts and must preserve blocked/stale/unreviewed/unsupported/manual-trusted
limitations instead of converting them into trusted conclusions.

Frontend Advisor Brief surfaces consume the `structured_suggestions` field
from `GET /api/chat/suggestions` only when the caller explicitly sends
`include_structured=true`, and render structured facts directly rather than
parsing LLM prose; callers that only need the base suggested-question list
omit the flag so the endpoint stays lightweight. Any `next_action_href`
shown to users is normalized through the Advisor Brief safe-route allowlist
before rendering, and contextual chat-entry links seed scoped prompts
through `/chat?prompt=...` without clearing the user's existing session.

`POST /api/chat` is a text streaming endpoint; personal-data answers also
expose compact application-owned grounding metadata in the
`X-Advisor-Metadata` response header — `grounded`, `citations[]` (`label`,
`source_ref`, `confidence_tier`, `href`), and `actions[]` (`kind`, `label`,
`href`, optional `count`). Citations point to safe internal
report/advisor surfaces rather than raw account numbers, source files, or
transaction-level PII. Action chips are read-only deep links (e.g.
`Review N`) that must never execute ledger writes, approvals, postings, or
reconciliation mutations. The frontend renders this metadata directly and
must not infer citations or actions by parsing LLM prose.

Because the endpoint returns a bare `StreamingResponse` (no FastAPI
`response_model`), its out-of-band payload is declared by the typed
contract `ChatStreamEnvelope` (`apps/backend/src/schemas/streaming.py`): a
`text/plain` token body plus headers `X-Session-Id` (session UUID),
optional `X-Model-Name`, and optional `X-Advisor-Metadata` (validated
against `ChatResponseMetadata` before serialization; omitted when empty),
with `X-Session-Id`, `X-Model-Name`, and `X-Advisor-Metadata` listed in
`Access-Control-Expose-Headers` in that order (`AC-advisor.envelope.*`).

## Suggestion scope and data-handling policy

The assistant may surface explainable personal-finance suggestions from
trusted summary data, known data gaps, and pending review actions —
cash-flow observations, unusual income/expense movement, portfolio
concentration flags, stale market-data warnings, missing source documents,
report-readiness blockers, and questions the user should answer before
relying on a report. Suggestions are read-only: they must identify their
source basis or limitation and must not execute trades, mutate ledger data,
provide legal/tax advice, or present regulated investment advice as a
conclusion. Report package snapshots/export scale stay in `reporting`'s own
EPICs; manual evidence intake and source-format expansion stay in
`extraction`/`portfolio`'s own EPICs — the advisor only explains the
current application state and points to safe next actions.

- No ledger mutations, no write endpoints used.
- Only summarized data is sent to the LLM — no full account numbers or raw
  files.
- Sensitive fields are redacted before sending and after receiving.
- Provider-neutral `AI_*` configuration lets the base model change without
  an API contract change.

Recommended: use `JournalEntry.status in (posted, reconciled)` for any
financial context; build prompts with explicit role boundaries and a
disclaimer requirement; limit LLM context to the last 10 message pairs;
store all messages in `chat_messages` for audit/history. Prohibited: never
send full account numbers, passwords, or credentials to the LLM; never let
the AI write or delete ledger data; never fabricate financial figures when
source data is missing; never return a response without the required
disclaimer.

## Playbooks

- **Prompt-injection defense**: detect injection intent (ignore
  instructions, reveal system prompt, write data) → refuse with safe
  language → continue answering only within scope.
- **Missing model credentials**: detect a missing `ZAI_API_KEY`/`AI_API_KEY`
  → return 503 with a friendly message and no partial response → log the
  failure for audit.
- **Model selection**: the UI pulls available models from
  `/api/llm/catalog` (superseded the retired `/api/ai/models`); the client
  sends the selected `model` in `POST /api/chat`; if omitted, the service
  uses `PRIMARY_MODEL` and may try `FALLBACK_MODELS`. Statement OCR uses
  `OCR_MODEL` (falls back to the shared vision OCR path when no separate
  layout-parsing API exists) and stores transaction amounts as non-negative
  `Decimal` with `direction` as the sign source — signed model outputs like
  `{"amount": "-500.00", "direction": "OUT"}` are normalized before balance
  validation and routing.
- **Cached common Q&A**: normalize the user question and language → check
  the cache before calling the LLM → store responses with a TTL to reduce
  cost (see [Cache](#cache) above).
