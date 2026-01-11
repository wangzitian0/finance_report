# AI Advisor API

The AI Advisor API provides a streaming chat interface for financial insights. Responses are streamed as plain text.

## POST /api/chat

Send a chat message and receive a streaming response.

### Request

```json
{
  "message": "What are my expenses this month?",
  "session_id": "optional-session-id"
}
```

### Response

- **Content-Type**: `text/plain`
- **Streaming**: Yes
- **Headers**:
  - `X-Session-Id`: Chat session identifier

The response body streams text. Each response ends with a disclaimer line:

```
The above analysis is for reference only.
```

## GET /api/chat/history

Retrieve chat history. Use `session_id` to load messages for a specific session.

### Example

```bash
curl "/api/chat/history?session_id=<id>"
```

### Response

```json
{
  "sessions": [
    {
      "id": "...",
      "title": "...",
      "status": "active",
      "message_count": 4,
      "last_message": {
        "role": "assistant",
        "content": "...",
        "created_at": "2026-01-10T12:00:00Z"
      },
      "messages": [
        {
          "id": "...",
          "session_id": "...",
          "role": "user",
          "content": "...",
          "created_at": "2026-01-10T11:59:00Z"
        }
      ]
    }
  ]
}
```

## DELETE /api/chat/session/{id}

Soft-delete a chat session.

### Example

```bash
curl -X DELETE "/api/chat/session/<id>"
```

### Response

- Status: `204 No Content`

## GET /api/chat/suggestions

Return a list of suggested questions.

### Query Parameters

| Name | Type | Description |
|------|------|-------------|
| `language` | string | `en` or `zh` |
| `message` | string | Optional message to auto-detect language |

### Example

```bash
curl "/api/chat/suggestions?language=en"
```

### Response

```json
{
  "suggestions": [
    "What are my expenses this month?",
    "What is my current net worth?"
  ]
}
```
