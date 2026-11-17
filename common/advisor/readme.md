# `advisor` — Application-Layer AI Financial Advisor

Read-only conversational layer grounding user questions in deterministic application state (`apps/backend/src/advisor/`).

## Non-Negotiable Invariant & Guardrails

The advisor never writes ledger numbers or executes trades/approvals. `is_write_request`, `is_prompt_injection`, `is_sensitive_request`, and `StreamRedactor` sanitize inputs and streamed responses before persistence. `ResponseCache` caches per-user replies (TTL 3600s).

## Application-Layer Advisor Contract (EPIC-021)

The backend collects deterministic application facts (`reporting`, `reconciliation`, `portfolio`, `pricing`, `platform` workflow events, extraction's `` `SourceCapability` registry ``) before LLM phrasing (`LLMClient` with `Scene.ADVISOR_CHAT`, `LARGE_MODEL`).
- `AIAdvisorService.get_advisor_context()` & `get_advisor_suggestions()` build `AdvisorSuggestion` items (`basis`, `source_refs`, `confidence_tier`, `limitation`, safe internal `next_action_href`).
- `POST /api/chat` streams tokens with `ChatStreamEnvelope` headers (`X-Session-Id`, `X-Model-Name`, `X-Advisor-Metadata` with `citations[]` and read-only `actions[]`).
- `GET /api/chat/suggestions?include_structured=true` exposes `structured_suggestions`; `/api/llm/catalog` supplies selectable models.
