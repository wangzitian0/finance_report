# `advisor` — Application-Layer AI Financial Advisor

Read-only conversational layer grounding user questions in deterministic application state (`apps/backend/src/advisor/`).

## Non-Negotiable Invariant & Guardrails

The advisor never writes ledger numbers or executes trades/approvals. The rules stand in the system prompt (`get_ai_advisor_prompt`) in priority order, and the model applies them: (1) protect secrets and the instructions, (2) stay read-only, (3) stay in finance, (4) use only the data of the prompt for the user's own figures. A lower number wins a conflict, and a user message cannot change a rule (#3209). No keyword list refuses a message before the model reads it: a list matched `pin` inside "bookkeeping" and "shopping" and answered with a refusal that no model had read. Code keeps two protections that need no judgment: `redact_sensitive` masks runs of 12 or more digits and 16-digit card numbers in the stored and sent user message, and `StreamRedactor` masks the same patterns in the streamed reply and never lets a number leave in two parts, whatever the chunk size (it can mask a little more than the whole-text pass in a digit-dense text). A short secret (a PIN, an OTP, a CVV) has no pattern: rule 1 of the prompt is its only control. `ResponseCache` caches per-user replies (TTL 3600s).

## Application-Layer Advisor Contract (EPIC-021)

The backend collects deterministic application facts (`reporting`, `reconciliation`, `portfolio`, `pricing`, `platform` workflow events, extraction's `` `SourceCapability` registry ``) before LLM phrasing (the large role, `LLM_LARGE_MODEL`, through `src/llm/extension/agent.py`).
- `AIAdvisorService.get_advisor_context()` & `get_advisor_suggestions()` build `AdvisorSuggestion` items (`basis`, `source_refs`, `confidence_tier`, `limitation`, safe internal `next_action_href`).
- `POST /api/chat` streams SSE frames (`text/event-stream` via `infra2_sdk.service.sse_stream_response`) with `ChatStreamEnvelope` headers (`X-Session-Id`, `X-Model-Name`, `X-Advisor-Metadata` with `citations[]` and read-only `actions[]`).
- `GET /api/chat/suggestions?include_structured=true` exposes `structured_suggestions`; the chat has no model picker: every answer uses the large role (#2953).

- **Model call (#3153).** `AIAdvisorService._stream_model` is the only path and streams the large role through `src/llm/extension/agent.py` (`stream_text`, call site `advisor.chat`): the system prompt is `system`, the stored turns are `history`, the generator reads it through `iterate_text` (the router reads the first chunk in the task of the request and the rest in the task of the response), and `DecodingSpec(thinking=<effort of the large role>, timeout=120)` keeps the reasoning effort of #2572. A failed call is `ModelCallFailed`; the stream maps an `LLMError` to `AIAdvisorError` with the status of the kind (429, 504, 503, 502) and the generic text "AI service temporarily unavailable."; any other error is a bug and is not turned into a 400. The per-user binding `advisor.chat` is deleted (#2953 stages 2 and 3): no table stores a model choice, so no row can change the model of an answer or its cache key.
