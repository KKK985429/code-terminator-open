import type {
  AgentStatusResponse,
  ChatHistoryResponse,
  ChatStreamDeltaEvent,
  ChatStreamLogEvent,
  ChatStreamStartEvent,
  ChatSendResponse,
  ConversationListResponse,
  PlanSnapshotResponse,
  RuntimeSettings,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return (await response.json()) as T;
}

export function fetchAgentStatus(): Promise<AgentStatusResponse> {
  return request<AgentStatusResponse>("/api/agents/status");
}

export function fetchConversations(): Promise<ConversationListResponse> {
  return request<ConversationListResponse>("/api/chat/history");
}

export function fetchConversation(conversationId: string): Promise<ChatHistoryResponse> {
  return request<ChatHistoryResponse>(`/api/conversations/${conversationId}`);
}

export function fetchRuntimeSettings(): Promise<RuntimeSettings> {
  return request<RuntimeSettings>("/api/settings/runtime");
}

export function fetchPlanSnapshot(conversationId: string): Promise<PlanSnapshotResponse> {
  return request<PlanSnapshotResponse>(`/api/conversations/${conversationId}/plan`);
}

export function saveRuntimeSettings(githubToken: string): Promise<RuntimeSettings> {
  return request<RuntimeSettings>("/api/settings/runtime", {
    method: "PUT",
    body: JSON.stringify({
      github_token: githubToken,
    }),
  });
}

export function sendMessage(
  message: string,
  conversationId?: string
): Promise<ChatSendResponse> {
  return request<ChatSendResponse>("/api/chat/send", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
    }),
  });
}

type StreamHandlers = {
  onStart?: (event: ChatStreamStartEvent) => void;
  onDelta?: (event: ChatStreamDeltaEvent) => void;
  onDone?: (event: ChatSendResponse) => void;
  onPlan?: (event: PlanSnapshotResponse) => void;
  onLog?: (event: ChatStreamLogEvent) => void;
  onError?: (message: string) => void;
};

export async function sendMessageStream(
  message: string,
  conversationId: string | undefined,
  handlers: StreamHandlers
): Promise<void> {
  const response = await fetch("/api/chat/send/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  if (!response.body) {
    throw new Error("流式响应不可用");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const lines = frame
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const eventLine = lines.find((line) => line.startsWith("event:"));
      const dataLine = lines.find((line) => line.startsWith("data:"));
      if (!eventLine || !dataLine) {
        continue;
      }
      const eventType = eventLine.slice("event:".length).trim();
      const payload = JSON.parse(dataLine.slice("data:".length).trim()) as unknown;
      if (eventType === "start") {
        handlers.onStart?.(payload as ChatStreamStartEvent);
      } else if (eventType === "delta") {
        handlers.onDelta?.(payload as ChatStreamDeltaEvent);
      } else if (eventType === "done") {
        handlers.onDone?.(payload as ChatSendResponse);
      } else if (eventType === "plan") {
        handlers.onPlan?.(payload as PlanSnapshotResponse);
      } else if (eventType === "log") {
        handlers.onLog?.(payload as ChatStreamLogEvent);
      } else if (eventType === "error") {
        const detail = String((payload as { message?: string }).message ?? "流式发送失败");
        handlers.onError?.(detail);
      }
    }
  }
}
