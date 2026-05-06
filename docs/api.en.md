# API Reference

This document describes the HTTP API exposed by the Code Terminator backend.

In development mode, the backend listens on:

```text
http://127.0.0.1:18000
```

If you start `uvicorn` manually, the host and port can be changed. The examples below use the default `18000` port.

OpenAPI endpoints:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

All runtime APIs are mounted under `/api`.

## Health

### `GET /api/health`

Returns backend health and startup metadata.

Example response:

```json
{
  "status": "ok",
  "service": "code-terminator-api",
  "started_at": "2026-04-16T10:00:00+00:00"
}
```

## Agent Status

### `GET /api/agents/status`

Returns a compact status summary for runtime roles.

Example response:

```json
{
  "roles": [
    {
      "role": "leader",
      "status": "idle",
      "active_count": 1,
      "busy_count": 0,
      "last_task": "",
      "last_activity": "2026-04-16T10:00:00+00:00"
    },
    {
      "role": "worker",
      "status": "idle",
      "active_count": 0,
      "busy_count": 0,
      "last_task": "",
      "last_activity": "2026-04-16T10:00:00+00:00"
    },
    {
      "role": "reviewer",
      "status": "idle",
      "active_count": 0,
      "busy_count": 0,
      "last_task": "",
      "last_activity": "2026-04-16T10:00:00+00:00"
    }
  ]
}
```

## Chat

### `POST /api/chat/send`

Runs a non-streaming chat or task request.

Example request:

```json
{
  "message": "Summarize the current plan",
  "conversation_id": "conv-1234abcd"
}
```

Fields:

| Field | Required | Description |
| --- | --- | --- |
| `message` | Yes | User message or task instruction |
| `conversation_id` | No | Existing conversation ID; if omitted, the backend creates a new conversation |

Example response:

```json
{
  "conversation_id": "conv-1234abcd",
  "thread_id": "conv-1234abcd",
  "reply": "Agent response content",
  "agent_status": {
    "roles": [
      {
        "role": "leader",
        "status": "idle",
        "active_count": 1,
        "busy_count": 0,
        "last_task": "Summarize the current plan",
        "last_activity": "2026-04-16T10:00:02+00:00"
      }
    ]
  },
  "plan_items": [],
  "react_trace": [],
  "activity_log": []
}
```

### `POST /api/chat/send/stream`

Runs a streaming chat or task request and returns `text/event-stream`.

The endpoint emits these SSE event types:

| Event | Description |
| --- | --- |
| `start` | Stream has started |
| `delta` | Incremental assistant output |
| `log` | Runtime activity log entry |
| `plan` | Plan snapshot update |
| `done` | Stream finished successfully |
| `error` | Stream failed |

The web console uses this endpoint for streaming messages, activity logs, and plan panel updates.

Example request body:

```json
{
  "message": "Fix the failing order service test",
  "conversation_id": "conv-1234abcd"
}
```

## History

### `GET /api/chat/history`

Lists known conversations.

Example response:

```json
{
  "conversations": [
    {
      "conversation_id": "conv-1234abcd",
      "thread_id": "conv-1234abcd",
      "message_count": 2,
      "updated_at": "2026-04-16T10:00:02+00:00"
    }
  ]
}
```

### `GET /api/conversations/{conversation_id}`

Returns persisted messages for a conversation.

Example response:

```json
{
  "conversation_id": "conv-1234abcd",
  "messages": [
    {
      "message_id": "msg-aabbccdd",
      "conversation_id": "conv-1234abcd",
      "role": "user",
      "content": "Summarize the current plan",
      "created_at": "2026-04-16T10:00:00+00:00"
    },
    {
      "message_id": "msg-eeff0011",
      "conversation_id": "conv-1234abcd",
      "role": "assistant",
      "content": "Agent response content",
      "created_at": "2026-04-16T10:00:02+00:00"
    }
  ]
}
```

### `GET /api/conversations/{conversation_id}/plan`

Returns the latest plan snapshot for a conversation.

Example response:

```json
{
  "conversation_id": "conv-1234abcd",
  "plan_items": [
    {
      "task_id": "task-1",
      "content": "Split repository refactor task",
      "status": "in_progress",
      "details": "",
      "response": "",
      "assignee": "worker",
      "updated_at": "2026-04-16T10:00:05+00:00"
    }
  ],
  "react_trace": [],
  "activity_log": [],
  "list_plan_text": "",
  "updated_at": "2026-04-16T10:00:05+00:00"
}
```

## Runtime Settings

### `GET /api/settings/runtime`

Reads persisted runtime settings.

Example response:

```json
{
  "github_token": "",
  "updated_at": "2026-04-16T10:00:00+00:00"
}
```

### `PUT /api/settings/runtime`

Updates persisted runtime settings.

Example request:

```json
{
  "github_token": "ghp_xxx"
}
```

The response body matches `GET /api/settings/runtime`.

By default, settings are written to:

```text
.code-terminator/runtime-state/settings/runtime.json
```

## Error Handling

The API uses standard FastAPI JSON error responses.

Common status codes:

| Status | Description |
| --- | --- |
| `200` | Success |
| `422` | Request validation failed |
| `500` | Runtime error |

## Local Development

Start the backend:

```bash
uv run uvicorn src.api.app:app --reload --host 127.0.0.1 --port 18000
```

Start the full stack dev environment:

```bash
npm run dev
```

The frontend development server proxies `/api` requests to the backend.
