# AI SSOT

> **SSOT Key**: `ai`
> **Core Definition**: Conversational financial advisor behavior, data scope, prompt policy, and safety controls.

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

---

## 2. Architecture Model

### 2.1 Read-Only Flow

```mermaid
flowchart LR
    U[User] --> UI[Chat UI]
    UI --> API[POST /api/chat]
    API --> CTX[Build Financial Context]
    CTX --> LLM[OpenRouter Model (default PRIMARY_MODEL)]
    LLM --> API
    API --> UI
```

### 2.2 Context Assembly

The advisor only reads summarized, posted/reconciled data:

- Balance sheet totals (posted/reconciled only)
- Income statement totals for the current month
- Top expense categories (monthly)
- Reconciliation stats and unmatched counts
- User session context (last 10 rounds max)

### 2.3 Data Handling Policy

- No ledger mutations, no write endpoints used.
- Only summarized data is sent to the LLM (no full account numbers or raw files).
- Sensitive fields are redacted before sending and after receiving.
- The architecture allows a future local model swap without changing API contracts.

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

1. Detect missing `OPENROUTER_API_KEY`.
2. Return 503 with a friendly message and no partial response.
3. Log the failure for audit.

### SOP-004: Model Selection

1. UI pulls available models from `/api/ai/models`.
2. Client sends the selected `model` in `POST /api/chat`.
3. If omitted, the service uses `PRIMARY_MODEL` with fallbacks.

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

---

## Used by

- [schema.md](./schema.md)
- [reporting.md](./reporting.md)
- [reconciliation.md](./reconciliation.md)
