export type AgentStatus = {
  role: "leader" | "worker" | "reviewer";
  status: "idle" | "busy" | "error";
  active_count: number;
  busy_count: number;
  last_task: string;
  last_activity: string;
};

export type AgentStatusResponse = {
  roles: AgentStatus[];
};

export type ChatMessage = {
  message_id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type ConversationSummary = {
  conversation_id: string;
  thread_id: string;
  message_count: number;
  updated_at: string;
};

export type ConversationListResponse = {
  conversations: ConversationSummary[];
};

export type ChatHistoryResponse = {
  conversation_id: string;
  messages: ChatMessage[];
};

export type RuntimeSettings = {
  github_token: string;
  updated_at: string;
};

export type PlanStatus = "pending" | "in_progress" | "completed" | "failed";
export type PlanAssignee = "leader" | "worker" | "reviewer" | "unassigned";

export type PlanItem = {
  task_id: string;
  content: string;
  status: PlanStatus;
  details: string;
  response: string;
  assignee: PlanAssignee;
  updated_at: string;
};

export type ReactStep = {
  step: number;
  thought: string;
  action_name: string;
  action_arguments: Record<string, unknown>;
  is_final: boolean;
  final_reply: string;
  observation_summary: string;
};

export type ActivityLogEntry = {
  entry_id: string;
  message: string;
  kind: "info" | "success" | "warning" | "error";
  created_at: string;
};

export type PlanSnapshotResponse = {
  conversation_id: string;
  plan_items: PlanItem[];
  react_trace: ReactStep[];
  activity_log: ActivityLogEntry[];
  list_plan_text: string;
  updated_at: string;
};

export type ChatSendResponse = {
  conversation_id: string;
  thread_id: string;
  reply: string;
  agent_status: AgentStatusResponse;
  plan_items: PlanItem[];
  react_trace: ReactStep[];
  activity_log: ActivityLogEntry[];
};

export type ChatStreamStartEvent = {
  conversation_id: string;
  thread_id: string;
};

export type ChatStreamDeltaEvent = {
  delta: string;
};

export type ChatStreamLogEvent = ActivityLogEntry;
