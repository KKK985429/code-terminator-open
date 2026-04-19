# API Reference

开发模式下，后端默认监听：

```text
http://127.0.0.1:18000
```

如果你手动启动 `uvicorn`，端口可以自行调整；下面示例仍使用 `18000`。

OpenAPI:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

所有运行时接口都挂在 `/api` 之下。

## Health

### `GET /api/health`

响应示例：

```json
{
  "status": "ok",
  "service": "code-terminator-api",
  "started_at": "2026-04-16T10:00:00+00:00"
}
```

## Agent Status

### `GET /api/agents/status`

响应示例：

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

请求示例：

```json
{
  "message": "帮我总结当前计划",
  "conversation_id": "conv-1234abcd"
}
```

- `conversation_id` 可选；不传时后端会创建新会话。

响应示例：

```json
{
  "conversation_id": "conv-1234abcd",
  "thread_id": "conv-1234abcd",
  "reply": "主 agent 回复内容",
  "agent_status": {
    "roles": [
      {
        "role": "leader",
        "status": "idle",
        "active_count": 1,
        "busy_count": 0,
        "last_task": "帮我总结当前计划",
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

返回 `text/event-stream`。当前会发出这些 SSE event：

- `start`
- `delta`
- `log`
- `plan`
- `done`
- `error`

前端使用这个接口做流式渲染、活动日志和计划面板刷新。

## History

### `GET /api/chat/history`

响应示例：

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

响应示例：

```json
{
  "conversation_id": "conv-1234abcd",
  "messages": [
    {
      "message_id": "msg-aabbccdd",
      "conversation_id": "conv-1234abcd",
      "role": "user",
      "content": "帮我总结当前计划",
      "created_at": "2026-04-16T10:00:00+00:00"
    },
    {
      "message_id": "msg-eeff0011",
      "conversation_id": "conv-1234abcd",
      "role": "assistant",
      "content": "主 agent 回复内容",
      "created_at": "2026-04-16T10:00:02+00:00"
    }
  ]
}
```

### `GET /api/conversations/{conversation_id}/plan`

响应示例：

```json
{
  "conversation_id": "conv-1234abcd",
  "plan_items": [
    {
      "task_id": "task-1",
      "content": "拆分仓库重构任务",
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

响应示例：

```json
{
  "github_token": "",
  "updated_at": "2026-04-16T10:00:00+00:00"
}
```

### `PUT /api/settings/runtime`

请求示例：

```json
{
  "github_token": "ghp_xxx"
}
```

响应体与 `GET /api/settings/runtime` 相同。

默认会写入：

```text
.code-terminator/runtime-state/settings/runtime.json
```

## Error Handling

- 使用 FastAPI 默认 JSON 错误响应
- 常见状态码：
  - `200` 成功
  - `422` 请求参数校验失败
  - `500` 运行时错误
