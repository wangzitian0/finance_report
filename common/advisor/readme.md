# `advisor` — Application-Layer AI Financial Advisor

Read-only conversational layer grounding user questions in deterministic application state (`apps/backend/src/advisor/`).

## Non-Negotiable Invariant & Guardrails

The advisor never writes ledger numbers or executes trades/approvals. `is_write_request`, `is_prompt_injection`, `is_sensitive_request`, and `StreamRedactor` sanitize inputs and streamed responses before persistence. `ResponseCache` caches per-user replies (TTL 3600s).

## Application-Layer Advisor Contract (EPIC-021)

The backend collects deterministic application facts (`reporting`, `reconciliation`, `portfolio`, `pricing`, `platform` workflow events, extraction's `` `SourceCapability` registry ``) before LLM phrasing (the large role, `LLM_LARGE_MODEL`, through `src/llm/extension/agent.py`).
- `AIAdvisorService.get_advisor_context()` & `get_advisor_suggestions()` build `AdvisorSuggestion` items (`basis`, `source_refs`, `confidence_tier`, `limitation`, safe internal `next_action_href`).
- `POST /api/chat` streams tokens with `ChatStreamEnvelope` headers (`X-Session-Id`, `X-Model-Name`, `X-Advisor-Metadata` with `citations[]` and read-only `actions[]`).
- `GET /api/chat/suggestions?include_structured=true` exposes `structured_suggestions`; the chat has no model picker: every answer uses the large role (#2953).

- **Model call (#3153).** `AIAdvisorService._stream_model` is the only path and streams the large role through `src/llm/extension/agent.py` (`stream_text`, call site `advisor.chat`): the system prompt is `system`, the stored turns are `history`, the generator reads it through `iterate_text` (the router reads the first chunk in the task of the request and the rest in the task of the response), and `DecodingSpec(thinking=<effort of the large role>, timeout=120)` keeps the reasoning effort of #2572. A failed call is `ModelCallFailed`; the stream maps an `LLMError` to `AIAdvisorError` with the status of the kind (429, 504, 503, 502) and the generic text "AI service temporarily unavailable."; any other error is a bug and is not turned into a 400. The per-user binding `advisor.chat` is deleted (#2953 stage 2): a row in `llm_scene_bindings` changes neither the model of an answer nor its cache key.
