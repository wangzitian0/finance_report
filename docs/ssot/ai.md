# AI SSOT

> **SSOT Key**: `ai`
> **Core Definition**: Application-layer AI Advisor behavior, data scope,
> prompt policy, contextual suggestion contract, and safety controls.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Service** | `apps/backend/src/services/ai_advisor.py` | Prompt construction, context building, safety filters |
| **API Router** | `apps/backend/src/routers/chat.py` | Chat endpoints and streaming responses |
| **Models** | `apps/backend/src/models/chat.py` | Chat session/message persistence |
| **Schemas** | `apps/backend/src/schemas/chat.py` | Request/response validation |
| **Prompt Templates** | `apps/backend/src/prompts/ai_advisor.py` | System prompt + injection guardrails |
| **Frontend UI** | `apps/frontend/src/app/chat/page.tsx` | Full chat experience |
| **Chat Widget** | `apps/frontend/src/components/ChatWidget.tsx` | Floating assistant entry point |
| **Application EPIC** | `docs/project/EPIC-021.application-ai-advisor.md` | Advisor Brief product contract and application-layer ownership |
| **Source Trust** | `docs/ssot/source-coverage-matrix.yaml` | source coverage matrix consumed for trust and limitation explanations |
| **Workflow State** | `docs/ssot/workflow-events.md` | Upload-to-report state and blockers consumed by Advisor Brief |

---

## 2. Architecture Model

### 2.1 Read-Only Flow

```mermaid
flowchart LR
    U[User] --> UI[Chat UI]
    UI --> API[POST /api/chat]
    API --> CTX[Build Financial Context]
    CTX --> LLM[Configured AI Provider (default PRIMARY_MODEL)]
    LLM --> API
    API --> UI
```

### 2.2 Context Assembly

The advisor only reads summarized, posted/reconciled data and deterministic
application facts. It is an application-layer consumer, not the source of
record.

- Balance sheet totals (posted/reconciled only)
- Income statement totals for the current month
- Top expense categories (monthly)
- Reconciliation stats and unmatched counts
- User session context (last 10 rounds max)

### 2.3 Application-Layer Advisor Contract

EPIC-021 upgrades Advisor behavior from generic chat to product guidance. The
backend must assemble deterministic application facts first; the LLM may only
explain, prioritize, and phrase those facts.

Application context may include:

- Report package readiness, snapshot/export status, and traceability gaps from
  reporting SSOT.
- Upload-to-report workflow events, blocked steps, pending review state, and
  next available actions from workflow events.
- Source class trust, proof level, review requirement, and unsupported source
  limitations from the source coverage matrix.
- Portfolio holdings, concentration, valuation, and performance facts from the
  portfolio/reporting layer.
- Market-data freshness and stale-price warnings from market data SSOT.
- Cash-flow observations from posted/reconciled ledger summaries.

The Advisor output contract for a structured suggestion is:

- `basis`: deterministic application fact or user question that triggered the
  suggestion.
- `source_refs`: internal report, workflow, source, portfolio, or market-data
  references that support the suggestion.
- `confidence_tier`: deterministic, review_required, stale, unsupported, or
  blocked.
- `limitation`: what the user should not rely on yet.
- `next_action_href`: safe internal route for the next in-product action.

Backend implementation uses `AIAdvisorService.get_advisor_context()` as the
deterministic advisor-fact assembly boundary. It composes legacy financial
summary fields with report package readiness, source trust, workflow status,
market-data freshness, portfolio summary, cash-flow observations, and
`AdvisorSuggestion` objects before prompt construction. The prompt receives the
serialized structured facts and must preserve blocked, stale, unreviewed,
unsupported, and manual-trusted limitations instead of converting them into
trusted conclusions.

Frontend Advisor Brief surfaces consume the `structured_suggestions` response
field from `GET /api/chat/suggestions` only when they explicitly send
`include_structured=true`; they must render structured facts directly rather
than parsing LLM prose. Callers that only need the base suggested-question list
must omit the flag so the endpoint remains lightweight. Any `next_action_href`
shown to users must be normalized through the Advisor Brief safe-route allowlist
before link rendering, and contextual chat entry links must seed scoped prompts
through `/chat?prompt=...` without clearing the user's existing chat session.

`POST /api/chat` remains a text streaming endpoint, but personal-data answers
also expose compact application-owned grounding metadata in the
`X-Advisor-Metadata` response header. The header contains only summarized
metadata: `grounded`, `citations[]` (`label`, `source_ref`,
`confidence_tier`, `href`) and `actions[]` (`kind`, `label`, `href`, optional
`count`). Citations point to safe internal report/advisor surfaces rather than
raw account numbers, source files, or transaction-level PII. Action chips are
read-only deep links such as `Review N`; they must never execute ledger writes,
approvals, postings, or reconciliation mutations. The frontend must render this
metadata directly and must not infer citations or actions by parsing LLM prose.

Because the endpoint returns a bare `StreamingResponse` (no FastAPI
`response_model`), its out-of-band payload is declared by the typed contract
`ChatStreamEnvelope` (`apps/backend/src/schemas/streaming.py`). The envelope
fixes the wire structure: a `text/plain` token body plus headers
`X-Session-Id` (session UUID), optional `X-Model-Name`, and optional
`X-Advisor-Metadata` (validated against `ChatResponseMetadata` before
serialization; omitted when the metadata is empty), with `X-Session-Id`,
`X-Model-Name`, and `X-Advisor-Metadata` listed in `Access-Control-Expose-Headers`
in that order. This is a description of the existing wire behavior, not a change
to it (EPIC-006 AC6.33).

### 2.4 Financial Suggestion Scope

The assistant may surface explainable personal-finance suggestions from trusted
summary data, known data gaps, and pending review actions. Supported suggestion
classes include cash-flow observations, unusual income or expense movement,
portfolio concentration flags, stale market-data warnings, missing source
documents, report-readiness blockers, and questions the user should answer
before relying on a report.

Suggestions are read-only. They must identify the source basis or limitation
behind the suggestion and must not execute trades, mutate ledger data, provide
legal or tax advice, or present regulated investment advice as a conclusion.

Report package snapshots and export scale stay in EPIC-005 / EPIC-008. Manual
evidence intake stays in EPIC-011 / EPIC-005. Source format expansion and parser
confidence stay in EPIC-003 / EPIC-013. EPIC-021 only explains the current
application state and points to safe next actions.

### 2.5 Data Handling Policy

- No ledger mutations, no write endpoints used.
- Only summarized data is sent to the LLM (no full account numbers or raw files).
- Sensitive fields are redacted before sending and after receiving.
- The architecture uses provider-neutral `AI_*` configuration so the base model can be changed without API contract changes.

---

## 3. Design Constraints (Dos and Don'ts)

### Recommended Patterns

- Use `JournalEntry.status in (posted, reconciled)` for any financial context.
- Build prompts with explicit role boundaries and disclaimer requirement.
- Use streaming responses for UI typing experience.
- Limit LLM context to the last 10 message pairs.
- Store all messages in `chat_messages` for audit and history.

### Prohibited Patterns

- Never send full account numbers, passwords, or credentials to the LLM.
- Never allow the AI to write or delete ledger data.
- Never fabricate financial figures if source data is missing.
- Never return responses without the required disclaimer.

---

## 4. Data Model (Schema Notes)

### ChatSession

- `id` UUID PK
- `user_id` UUID FK
- `title` string (optional auto title)
- `status` enum: `active`, `deleted`
- `created_at`, `updated_at`, `last_active_at`

### ChatMessage

- `id` UUID PK
- `session_id` UUID FK
- `role` enum: `user`, `assistant`, `system`
- `content` text (redacted if needed)
- `tokens_in`, `tokens_out` (estimated)
- `model_name`
- `created_at`

---

## 5. Standard Operating Procedures (Playbooks)

### SOP-001: Prompt Injection Defense

1. Detect injection intent (ignore instructions, reveal system prompt, write data).
2. Refuse the request with safe language.
3. Continue to answer only within scope.

### SOP-002: Missing Model Credentials

1. Detect missing `ZAI_API_KEY` / `AI_API_KEY`.
2. Return 503 with a friendly message and no partial response.
3. Log the failure for audit.

### SOP-004: Model Selection

1. UI pulls available models from `/api/ai/models`.
2. Client sends the selected `model` in `POST /api/chat`.
3. If omitted, the service uses `PRIMARY_MODEL` and may try `FALLBACK_MODELS` for chat responses.
4. Statement OCR uses `OCR_MODEL`; if it is separate from `VISION_MODEL`, the provider layout parsing API runs first, otherwise the shared vision OCR path is used directly.
5. Statement OCR stores transaction amounts as non-negative `Decimal` values and uses `direction` as the sign source. Signed model outputs such as `{"amount": "-500.00", "direction": "OUT"}` are normalized before balance validation and routing.
6. The post-merge staging brokerage gate uses the same configured OCR path for PDF uploads. It does not mock OCR: Moomoo and Futu PDF fixtures are sent through `/api/statements/upload`, then parsed statements are imported into portfolio positions through `/api/statements/{id}/brokerage/import`.

### SOP-003: Cached Common Q&A

1. Normalize user question and language.
2. Check cache before calling the LLM.
3. Store responses with TTL to reduce cost.

---

## 6. Verification (The Proof)

| Behavior | Verification Method | Status |
|----------|---------------------|--------|
| Streaming reply + injection refusal | `test_chat_refusal_and_history` | ✅ Done |
| Disclaimer appended | `test_chat_refusal_and_history` | ✅ Done |
| Session history | `test_chat_refusal_and_history` | ✅ Done |
| Suggestions endpoint | `test_chat_suggestions` | ✅ Done |
| Real OCR brokerage upload → portfolio value | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value` | ✅ Staging gate |
| EPIC-021 application-layer contract | `test_AC21_1_1_ai_advisor_is_application_layer_contract`, `test_AC21_1_2_scale_and_confidence_work_stays_in_existing_epics` | ✅ Framing |
| EPIC-021 backend advisor context | `test_AC21_2_1_advisor_context_includes_readiness_trust_workflow_and_suggestions`, `test_AC21_2_2_prompt_consumes_structured_advisor_facts_without_trusting_blocked_state`, `test_AC21_2_3_chat_stream_redacts_sensitive_numbers_before_provider_and_persistence` | ✅ Backend context |
| EPIC-022 grounded chat metadata | `test_AC22_14_3_chat_grounding_metadata_links_pending_review_without_write_actions`, `test_AC22_14_1_chat_response_exposes_grounding_metadata_header`, `chatPanelComponent.test.tsx` | ✅ Grounded chat |

---

## Used by

- [schema.md](./schema.md)
- [reporting.md](./reporting.md)
- [reconciliation.md](./reconciliation.md)
- [workflow-events.md](./workflow-events.md)
- [source-coverage-matrix.yaml](./source-coverage-matrix.yaml)
- [EPIC-021](../project/EPIC-021.application-ai-advisor.md)
