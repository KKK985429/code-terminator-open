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

export type AgentHealthResponse = {
  ingest_enabled: boolean;
  log_file: string;
  log_file_exists: boolean;
  last_log_offset: number;
  incident_total: number;
  incident_by_status: Record<string, number>;
  planner_active: string;
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

export type IncidentEntry = {
  fingerprint: string;
  status: string;
  thread_id: string;
  first_seen_at: string;
  occurrence_total: number;
  service: string;
  exception_type: string;
  sample_traceback: string;
  sample_trace_id?: string;
  last_seen_at: string;
  deployed_commit?: string;
  deployed_at?: string;
  verify_window_until?: string;
};

export type IncidentListResponse = {
  total: number;
  incidents: IncidentEntry[];
};

export type ChatHistoryResponse = {
  conversation_id: string;
  messages: ChatMessage[];
};

export type RuntimeSettings = {
  github_token: string;
  auto_review_merge_reload: boolean;
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
