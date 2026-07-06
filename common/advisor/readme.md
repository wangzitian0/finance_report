# `advisor` — application-layer AI financial advisor

> The spec + review surface for the ``advisor`` package.  Machine contract:
> [`contract.py`](./contract.py).  Worklist: [`todo.md`](./todo.md).
>
> This `common/advisor/` directory is the **spec surface**; the conforming
> implementation currently lives at
> [`apps/backend/src/services/ai_advisor`](../../apps/backend/src/services/ai_advisor)
> and will move to
> [`apps/backend/src/advisor`](../../apps/backend/src/advisor)
> (`contract.implementations["be"]`) in PR2.

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
- **`ChatSessionRepository`** — the repository port (base) + SQL adapter
  (extension); currently raw `AsyncSession` — port/adapter split is PR2
  scope.
- **`ChatHistoryView`** — the read-model projection: paginated chat history
  for the UI (list of sessions + messages, no write state).

## Read context (bounded, read-only)

The advisor aggregates context from:

| Source | What it reads | Where |
|--------|--------------|-------|
| `report_readiness` | Readiness state + blockers | `src.services.report_readiness` |
| `reporting` | Balance sheet, income statement, category breakdown | `src.services.reporting` |
| `reconciliation` | Pending review count, reconciliation stats | `src.services.reconciliation` |
| `portfolio` | Positions, unrealised P&L | `src.services.portfolio` |
| `market_data` | Scope status, prices | `src.services.market_data` |
| `workflow_events` | Action-required counts | `src.services.workflow_events` |

All reads are in the same `AsyncSession` transaction as the chat message
insert (the advisor's own transaction — `AC-advisor.txn.1`).  The advisor
never holds a reference to another domain's write objects.

## Layers (taxonomy declared; physical split is PR2)

The implementation will converge into the package model's internal layers
once the god-file `service.py` is split in PR2:

| Layer | What will live here |
|-------|---------------------|
| `base/` | `ChatSession` (AR), `ChatMessage` (entity), enums, VOs, `ChatSessionRepository` port |
| `extension/` | `AIAdvisorService`, `AdvisorGuardrails`, `ResponseCache`, `AdvisorSceneBinding`, SQL adapter |
| `extension/phases/` | `context_aggregation.py`, `prompt_construction.py`, `response_streaming.py` |
| `data/` | `ChatHistoryView` projection |

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
is_sensitive_request("My NRIC is S1234567A")         # True → refused
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
that prove them (added in PR2 when the physical split is done).
`tools/check_package_contract.py` validates the implementation against this
contract (interface == `__all__`, every test reference resolves, no upward
import edge).
