import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  fetchAgentHealth,
  fetchAgentStatus,
  fetchConversation,
  fetchConversations,
  fetchIncidents,
  fetchPlanSnapshot,
  fetchRuntimeSettings,
  saveRuntimeSettings,
  sendMessageStream,
} from "./api";
import type {
  ActivityLogEntry,
  AgentHealthResponse,
  AgentStatus,
  ChatMessage,
  ConversationSummary,
  IncidentEntry,
  PlanItem,
  PlanSnapshotResponse,
  PlanStatus,
  RuntimeSettings,
} from "./types";

const STATUS_LABELS: Record<PlanStatus, string> = {
  pending: "待开始",
  in_progress: "执行中",
  completed: "已完成",
  failed: "失败",
};

const AGENT_LABELS: Record<string, string> = {
  leader: "主 Agent",
  worker: "Worker",
  reviewer: "Reviewer",
  unassigned: "未分配",
};

const SUGGESTIONS: string[] = [
  "帮我梳理当前仓库的自动修复链路",
  "规划一次从异常发现到修复验证的任务流程",
  "分析前端控制台还能补哪些可观测能力",
];

function formatDateTime(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const pad = (n: number) => n.toString().padStart(2, "0");
  const hhmm = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (sameDay) return hhmm;
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hhmm}`;
}

function conversationTitle(c: ConversationSummary): string {
  return c.conversation_id.startsWith("conv-")
    ? `会话 ${c.conversation_id.slice(5, 13)}`
    : c.conversation_id;
}

function mergeActivityLog(
  current: ActivityLogEntry[],
  incoming: ActivityLogEntry[],
): ActivityLogEntry[] {
  const merged = new Map<string, ActivityLogEntry>();
  for (const entry of [...current, ...incoming]) {
    merged.set(entry.entry_id, entry);
  }
  return Array.from(merged.values()).sort((left, right) =>
    left.created_at.localeCompare(right.created_at),
  );
}

function incidentTitle(incident: IncidentEntry): string {
  return `${incident.service || "unknown-service"} · ${incident.exception_type || "UnknownError"}`;
}

function incidentStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    triaged: "已识别",
    running: "修复中",
    waiting_review: "待 Review",
    approved: "待部署",
    deployed: "已部署",
    resolved: "已解决",
    regressed: "复发",
    suppressed: "已忽略",
  };
  return labels[status] ?? status;
}

function incidentPlanStatus(
  incident: IncidentEntry,
  step: "dispatch" | "review" | "verify",
): PlanStatus {
  const status = incident.status;
  if (step === "dispatch") {
    if (status === "running") return "in_progress";
    if (
      status === "waiting_review" ||
      status === "approved" ||
      status === "deployed" ||
      status === "resolved"
    ) {
      return "completed";
    }
    return "pending";
  }
  if (step === "review") {
    if (status === "waiting_review" || status === "approved") return "in_progress";
    if (status === "deployed" || status === "resolved") return "completed";
    return "pending";
  }
  if (status === "deployed") return "in_progress";
  if (status === "resolved") return "completed";
  return "pending";
}

function buildIncidentPlan(
  incident: IncidentEntry,
  autoReviewMergeReload: boolean,
): PlanItem[] {
  const reviewLabel = autoReviewMergeReload
    ? "自动 Review / Merge"
    : "等待 Review / Merge";
  return [
    {
      task_id: `incident-${incident.fingerprint.slice(0, 8)}-detect`,
      content: "识别异常并建立 incident",
      status: "completed",
      details: `服务：${incident.service}\n异常：${incident.exception_type}\n故障指纹：${incident.fingerprint}`,
      response: "",
      assignee: "leader",
      updated_at: incident.first_seen_at,
    },
    {
      task_id: `incident-${incident.fingerprint.slice(0, 8)}-dispatch`,
      content: "派发 Worker 修复代码",
      status: incidentPlanStatus(incident, "dispatch"),
      details: `trace_id：${incident.sample_trace_id || "unknown"}\n最近出现：${incident.last_seen_at}`,
      response: "",
      assignee: "worker",
      updated_at: incident.last_seen_at,
    },
    {
      task_id: `incident-${incident.fingerprint.slice(0, 8)}-review`,
      content: reviewLabel,
      status: incidentPlanStatus(incident, "review"),
      details: incident.deployed_commit
        ? `部署提交：${incident.deployed_commit}`
        : "等待 Worker 产出分支和 PR。",
      response: "",
      assignee: "reviewer",
      updated_at: incident.deployed_at || incident.last_seen_at,
    },
    {
      task_id: `incident-${incident.fingerprint.slice(0, 8)}-verify`,
      content: "热重载并验证恢复",
      status: incidentPlanStatus(incident, "verify"),
      details: incident.verify_window_until
        ? `验证窗口截止：${incident.verify_window_until}`
        : "等待部署完成后进行回归验证。",
      response: "",
      assignee: "leader",
      updated_at:
        incident.verify_window_until ||
        incident.deployed_at ||
        incident.last_seen_at,
    },
  ];
}

function buildIncidentActivity(incident: IncidentEntry): ActivityLogEntry[] {
  const entries: ActivityLogEntry[] = [
    {
      entry_id: `incident-${incident.fingerprint}-created`,
      kind: "error",
      message: `检测到 ${incident.service} 的 ${incident.exception_type}，已累计 ${incident.occurrence_total} 次。`,
      created_at: incident.first_seen_at,
    },
    {
      entry_id: `incident-${incident.fingerprint}-running`,
      kind: incident.status === "resolved" ? "success" : "warning",
      message:
        incident.status === "resolved"
          ? "自动修复链路已完成验证，incident 已恢复。"
          : incident.status === "deployed"
            ? "修复已部署，正在等待热重载和验证结果。"
            : "Planner 已派发 Worker，正在生成分支、提交和 PR。",
      created_at: incident.last_seen_at,
    },
  ];
  if (incident.deployed_at) {
    entries.push({
      entry_id: `incident-${incident.fingerprint}-deployed`,
      kind: "success",
      message: `修复已部署，commit ${incident.deployed_commit?.slice(0, 12) || "unknown"}`,
      created_at: incident.deployed_at,
    });
  }
  return entries.sort((left, right) => left.created_at.localeCompare(right.created_at));
}

function incidentTracebackPreview(traceback: string): string {
  return traceback.split("\n").slice(0, 8).join("\n");
}

export function App() {
  const [agentStatus, setAgentStatus] = useState<AgentStatus[]>([]);
  const [agentHealth, setAgentHealth] = useState<AgentHealthResponse | null>(null);
  const [incidents, setIncidents] = useState<IncidentEntry[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>("");
  const [activeIncidentFingerprint, setActiveIncidentFingerprint] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [planSnapshot, setPlanSnapshot] = useState<PlanSnapshotResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null);
  const [githubTokenDraft, setGithubTokenDraft] = useState("");
  const [autoReviewMergeReloadDraft, setAutoReviewMergeReloadDraft] =
    useState(false);
  const [savingToken, setSavingToken] = useState(false);
  const [showGithubToken, setShowGithubToken] = useState(false);
  const [tokenStatus, setTokenStatus] = useState("");

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const logBackgroundError = useCallback((scope: string, err: unknown) => {
    const message = err instanceof Error ? err.message : String(err);
    console.warn(`[${scope}] ${message}`);
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    messagesEndRef.current?.scrollIntoView({ behavior, block: "end" });
  }, []);

  const refreshDashboard = useCallback(async () => {
    const [statusResp, conversationResp, incidentResp, healthResp] = await Promise.all([
      fetchAgentStatus(),
      fetchConversations(),
      fetchIncidents(),
      fetchAgentHealth(),
    ]);
    setAgentStatus(statusResp.roles);
    setConversations(conversationResp.conversations);
    setIncidents(incidentResp.incidents);
    setAgentHealth(healthResp);
  }, []);

  const loadConversation = useCallback(async (conversationId: string) => {
    if (!conversationId) {
      setMessages([]);
      setPlanSnapshot(null);
      return;
    }
    const [history, plan] = await Promise.all([
      fetchConversation(conversationId),
      fetchPlanSnapshot(conversationId).catch(() => null),
    ]);
    setMessages(history.messages);
    setPlanSnapshot(plan);
  }, []);

  useEffect(() => {
    void refreshDashboard().catch((err: Error) => setError(err.message));
    void fetchRuntimeSettings()
      .then((settings) => {
        setRuntimeSettings(settings);
        setGithubTokenDraft(settings.github_token);
        setAutoReviewMergeReloadDraft(settings.auto_review_merge_reload);
      })
      .catch((err: Error) => {
        logBackgroundError("fetchRuntimeSettings", err);
      });
    const timer = window.setInterval(() => {
      void refreshDashboard().catch((err: Error) => {
        logBackgroundError("refreshDashboard", err);
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [logBackgroundError, refreshDashboard]);

  useEffect(() => {
    if (
      !activeConversationId &&
      !activeIncidentFingerprint &&
      conversations.length > 0
    ) {
      setActiveConversationId(conversations[0].conversation_id);
    }
  }, [activeConversationId, activeIncidentFingerprint, conversations]);

  useEffect(() => {
    if (
      !activeConversationId &&
      !activeIncidentFingerprint &&
      incidents.length > 0
    ) {
      setActiveIncidentFingerprint(incidents[0].fingerprint);
    }
    if (
      activeIncidentFingerprint &&
      !incidents.some((item) => item.fingerprint === activeIncidentFingerprint)
    ) {
      setActiveIncidentFingerprint(incidents[0]?.fingerprint ?? "");
    }
  }, [activeConversationId, activeIncidentFingerprint, incidents]);

  useEffect(() => {
    if (loading) return;
    void loadConversation(activeConversationId).catch((err: Error) => {
      logBackgroundError("loadConversation", err);
    });
  }, [activeConversationId, loading, loadConversation, logBackgroundError]);

  useEffect(() => {
    scrollToBottom(streaming ? "auto" : "smooth");
  }, [messages, streaming, scrollToBottom]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  useEffect(() => {
    if (!activeConversationId) return;
    const timer = window.setInterval(() => {
      fetchPlanSnapshot(activeConversationId)
        .then((snap) => setPlanSnapshot(snap))
        .catch(() => undefined);
      fetchConversation(activeConversationId)
        .then((history) => {
          setMessages((prev) => {
            if (prev.length >= history.messages.length) return prev;
            return history.messages;
          });
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeConversationId]);

  const canSend = useMemo(
    () => input.trim().length > 0 && !loading,
    [input, loading],
  );
  const tokenDirty = runtimeSettings
    ? githubTokenDraft !== runtimeSettings.github_token ||
      autoReviewMergeReloadDraft !== runtimeSettings.auto_review_merge_reload
    : githubTokenDraft.length > 0 || autoReviewMergeReloadDraft;

  const displayedAgents = useMemo(() => {
    return agentStatus.filter(
      (item) => item.role === "leader" || item.active_count > 0 || item.busy_count > 0,
    );
  }, [agentStatus]);

  const activeIncident = useMemo(
    () =>
      incidents.find((incident) => incident.fingerprint === activeIncidentFingerprint) ??
      null,
    [activeIncidentFingerprint, incidents],
  );

  const incidentPlanSnapshot = useMemo(() => {
    if (!activeIncident) return null;
    return {
      conversation_id: activeIncident.thread_id,
      plan_items: buildIncidentPlan(
        activeIncident,
        autoReviewMergeReloadDraft,
      ),
      react_trace: [],
      activity_log: buildIncidentActivity(activeIncident),
      list_plan_text: "",
      updated_at: activeIncident.last_seen_at,
    } satisfies PlanSnapshotResponse;
  }, [activeIncident, autoReviewMergeReloadDraft]);

  const effectivePlanSnapshot =
    planSnapshot ?? (activeConversationId ? null : incidentPlanSnapshot);
  const effectivePlanItems = effectivePlanSnapshot?.plan_items ?? [];
  const effectiveActivityLog = effectivePlanSnapshot?.activity_log ?? [];

  const activeHeaderTitle = activeConversationId
    ? conversationTitle(
        conversations.find((c) => c.conversation_id === activeConversationId) ?? {
          conversation_id: activeConversationId,
          thread_id: "",
          message_count: 0,
          updated_at: "",
        },
      )
    : activeIncident
      ? `故障 ${activeIncident.fingerprint.slice(0, 8)}`
      : "新会话";

  const activeHeaderSubtitle = activeConversationId
    ? `thread · ${activeConversationId}`
    : activeIncident
      ? `${incidentTitle(activeIncident)} · ${incidentStatusLabel(activeIncident.status)}`
      : "发送第一条消息开始任务";

  const planStats = useMemo(() => {
    const counts: Record<PlanStatus, number> = {
      pending: 0,
      in_progress: 0,
      completed: 0,
      failed: 0,
    };
    for (const item of effectivePlanItems) counts[item.status] += 1;
    return counts;
  }, [effectivePlanItems]);

  function startNewConversation() {
    setActiveConversationId("");
    setActiveIncidentFingerprint("");
    setMessages([]);
    setPlanSnapshot(null);
    setInput("");
    textareaRef.current?.focus();
  }

  async function persistGithubToken(): Promise<void> {
    setSavingToken(true);
    setTokenStatus("");
    try {
      const saved = await saveRuntimeSettings(
        githubTokenDraft,
        autoReviewMergeReloadDraft,
      );
      setRuntimeSettings(saved);
      setGithubTokenDraft(saved.github_token);
      setAutoReviewMergeReloadDraft(saved.auto_review_merge_reload);
      setTokenStatus(saved.github_token ? "已保存到本地运行时配置" : "已清空本地运行时配置");
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存 token 失败";
      setTokenStatus(message);
    } finally {
      setSavingToken(false);
    }
  }

  async function submitMessage(text: string) {
    if (!text.trim() || loading) return;
    setLoading(true);
    setStreaming(true);
    setError("");
    const tempUserId = `tmp-user-${Date.now()}`;
    const tempAssistantId = `tmp-assistant-${Date.now()}`;
    const now = new Date().toISOString();
    setMessages((previous) => [
      ...previous,
      {
        message_id: tempUserId,
        conversation_id: activeConversationId || "pending",
        role: "user",
        content: text,
        created_at: now,
      },
      {
        message_id: tempAssistantId,
        conversation_id: activeConversationId || "pending",
        role: "assistant",
        content: "",
        created_at: now,
      },
    ]);
    setInput("");
    let streamedConversationId = activeConversationId;
    let receivedDone = false;
    try {
      await sendMessageStream(text, activeConversationId || undefined, {
        onStart: (event) => {
          streamedConversationId = event.conversation_id;
          setError("");
          setActiveIncidentFingerprint("");
          if (!activeConversationId) {
            setActiveConversationId(event.conversation_id);
          }
          setMessages((previous) =>
            previous.map((message) =>
              message.message_id === tempUserId ||
              message.message_id === tempAssistantId
                ? { ...message, conversation_id: event.conversation_id }
                : message,
            ),
          );
        },
        onDelta: (event) => {
          setMessages((previous) =>
            previous.map((message) =>
              message.message_id === tempAssistantId
                ? { ...message, content: `${message.content}${event.delta}` }
                : message,
            ),
          );
        },
        onDone: (event) => {
          receivedDone = true;
          streamedConversationId = event.conversation_id;
          setAgentStatus(event.agent_status.roles);
          setActiveConversationId(event.conversation_id);
          setActiveIncidentFingerprint("");
          setError("");
          if (
            event.plan_items?.length ||
            event.react_trace?.length ||
            event.activity_log?.length
          ) {
            setPlanSnapshot({
              conversation_id: event.conversation_id,
              plan_items: event.plan_items ?? [],
              react_trace: event.react_trace ?? [],
              activity_log: event.activity_log ?? [],
              list_plan_text: "",
              updated_at: new Date().toISOString(),
            });
          }
        },
        onPlan: (snap) => {
          setPlanSnapshot(snap);
          setError("");
        },
        onLog: (entry) => {
          setPlanSnapshot((previous) => ({
            conversation_id:
              previous?.conversation_id ||
              streamedConversationId ||
              activeConversationId ||
              "pending",
            plan_items: previous?.plan_items ?? [],
            react_trace: previous?.react_trace ?? [],
            activity_log: mergeActivityLog(previous?.activity_log ?? [], [entry]),
            list_plan_text: previous?.list_plan_text ?? "",
            updated_at: entry.created_at,
          }));
        },
        onError: (message) => {
          throw new Error(message);
        },
      });
      try {
        await refreshDashboard();
      } catch (err) {
        if (!receivedDone) {
          throw err;
        }
        logBackgroundError("post-send refreshDashboard", err);
      }
      try {
        await loadConversation(streamedConversationId || activeConversationId);
      } catch (err) {
        if (!receivedDone) {
          throw err;
        }
        logBackgroundError("post-send loadConversation", err);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "发送失败";
      setError(message);
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    await submitMessage(input);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSend) void submitMessage(input);
    }
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden />
          <div className="brand-text">
            <strong>Code Terminator</strong>
            <span>多 Agent 工作台</span>
          </div>
        </div>

        <button className="new-chat" onClick={startNewConversation} type="button">
          <span className="plus">+</span> 新建会话
        </button>

        <div className="sidebar-section">
          <div className="sidebar-section-head">
            <span>会话</span>
            <small>{conversations.length}</small>
          </div>
          <ul className="conversation-list">
            {conversations.map((conversation) => {
              const active = conversation.conversation_id === activeConversationId;
              return (
                <li key={conversation.conversation_id}>
                  <button
                    className={`conversation-item${active ? " active" : ""}`}
                    onClick={() => {
                      setActiveConversationId(conversation.conversation_id);
                      setActiveIncidentFingerprint("");
                    }}
                    disabled={loading}
                    type="button"
                  >
                    <div className="conversation-title">
                      {conversationTitle(conversation)}
                    </div>
                    <div className="conversation-meta">
                      <span>{conversation.message_count} 条消息</span>
                      <span>{formatDateTime(conversation.updated_at)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
            {conversations.length === 0 ? (
              <li className="conversation-empty">暂无会话</li>
            ) : null}
          </ul>
        </div>

        <div className="sidebar-section incident-section">
          <div className="sidebar-section-head">
            <span>自动修复</span>
            <small>{incidents.length}</small>
          </div>
          <ul className="conversation-list incident-list">
            {incidents.map((incident) => {
              const active =
                !activeConversationId &&
                incident.fingerprint === activeIncidentFingerprint;
              return (
                <li key={incident.fingerprint}>
                  <button
                    className={`conversation-item incident-item${active ? " active" : ""}`}
                    onClick={() => {
                      setActiveConversationId("");
                      setActiveIncidentFingerprint(incident.fingerprint);
                    }}
                    type="button"
                  >
                    <div className="conversation-title">{incidentTitle(incident)}</div>
                    <div className="conversation-meta">
                      <span>{incidentStatusLabel(incident.status)}</span>
                      <span>{formatDateTime(incident.last_seen_at)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
            {incidents.length === 0 ? (
              <li className="conversation-empty">暂无自动修复中的 incident</li>
            ) : null}
          </ul>
        </div>

        <div className="sidebar-footer">
          <div className="agent-strip">
            {displayedAgents.map((agent) => (
              <div key={agent.role} className={`agent-chip state-${agent.status}`}>
                <span className="agent-chip-dot" />
                <span>{AGENT_LABELS[agent.role] ?? agent.role}</span>
                {agent.role !== "leader" ? (
                  <small>{agent.active_count}</small>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          <div>
            <div className="main-title">{activeHeaderTitle}</div>
            <div className="main-subtitle">{activeHeaderSubtitle}</div>
          </div>
          <div className="main-actions">
            <span className={`status-dot ${loading ? "busy" : "idle"}`} />
            <span className="status-text">
              {loading ? "主 Agent 工作中" : "就绪"}
            </span>
          </div>
        </header>

        {error ? (
          <div className="error-banner" role="alert">
            <strong>运行出错：</strong>
            {error}
          </div>
        ) : null}

        <section className="runtime-settings-bar">
          <div className="runtime-settings-meta">
            <div>
              <strong>GitHub Token</strong>
              <span>Runtime credential</span>
            </div>
            <p>
              保存后会注入后端任务运行时，用于目标仓库的分支、提交和协作流程。
            </p>
          </div>
          <div className="runtime-settings-controls">
            <input
              className="token-input"
              type={showGithubToken ? "text" : "password"}
              value={githubTokenDraft}
              onChange={(e) => setGithubTokenDraft(e.target.value)}
              placeholder="未配置 GitHub token"
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              className="token-toggle-btn"
              onClick={() => setShowGithubToken((value) => !value)}
            >
              {showGithubToken ? "隐藏" : "显示"}
            </button>
            <button
              type="button"
              className="token-save-btn"
              disabled={savingToken || !tokenDirty}
              onClick={() => void persistGithubToken()}
            >
              {savingToken ? "保存中" : "保存"}
            </button>
            <label className="auto-review-toggle">
              <input
                type="checkbox"
                checked={autoReviewMergeReloadDraft}
                onChange={(e) => setAutoReviewMergeReloadDraft(e.target.checked)}
              />
              <span>自动 Review / Merge / 热重载</span>
            </label>
          </div>
          <div className="runtime-settings-hint">
            {tokenStatus ||
              (runtimeSettings?.updated_at
                ? `上次更新 ${formatDateTime(runtimeSettings.updated_at)}`
                : "保存后会作为后端任务的默认 GitHub 鉴权。")}
          </div>
        </section>

        <section className="chat-feed" aria-live="polite">
          {messages.length === 0 && activeIncident ? (
            <div className="incident-overview">
              <div className="empty-kicker">Incident Flow</div>
              <h2>{incidentTitle(activeIncident)}</h2>
              <p>
                当前状态：{incidentStatusLabel(activeIncident.status)}，已触发{" "}
                {activeIncident.occurrence_total} 次。前端现在会直接展示自动修复链路，不再依赖聊天会话生成。
              </p>
              <div className="incident-summary-grid">
                <div className="incident-summary-card">
                  <span>故障指纹</span>
                  <strong>{activeIncident.fingerprint}</strong>
                </div>
                <div className="incident-summary-card">
                  <span>Trace ID</span>
                  <strong>{activeIncident.sample_trace_id || "unknown"}</strong>
                </div>
                <div className="incident-summary-card">
                  <span>首次发现</span>
                  <strong>{formatDateTime(activeIncident.first_seen_at)}</strong>
                </div>
                <div className="incident-summary-card">
                  <span>最近出现</span>
                  <strong>{formatDateTime(activeIncident.last_seen_at)}</strong>
                </div>
              </div>
              <section className="incident-trace-card">
                <div className="plan-head">
                  <span>Traceback 片段</span>
                  <small>{activeIncident.exception_type}</small>
                </div>
                <pre className="incident-trace">
                  {incidentTracebackPreview(activeIncident.sample_traceback)}
                </pre>
              </section>
            </div>
          ) : messages.length === 0 ? (
            <div className="chat-empty">
              <div className="empty-kicker">Control Console</div>
              <h2>把复杂代码任务拆成可观察的执行流程</h2>
              <p>
                输入一个工程目标，系统会维护会话、计划、执行日志和运行时配置。你可以先配置 GitHub Token，再发起任务。
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="suggestion"
                    disabled={loading}
                    onClick={() => {
                      setInput(s);
                      textareaRef.current?.focus();
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-list">
              {messages.map((message) => {
                const isAssistant = message.role === "assistant";
                const isStreamingPlaceholder =
                  isAssistant && streaming && message.content === "";
                return (
                  <article
                    key={message.message_id}
                    className={`message ${isAssistant ? "assistant" : "user"}`}
                  >
                    <div className="avatar" aria-hidden>
                      {isAssistant ? "AG" : "我"}
                    </div>
                    <div className="message-body">
                      <div className="message-meta">
                        <strong>{isAssistant ? "主 Agent" : "你"}</strong>
                        <span>{formatDateTime(message.created_at)}</span>
                      </div>
                      <div className="message-content">
                        {isStreamingPlaceholder ? (
                          <span className="typing">
                            <i />
                            <i />
                            <i />
                          </span>
                        ) : (
                          message.content
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </section>

        <form onSubmit={onSubmit} className="composer">
          <div className="composer-inner">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="给主 Agent 发送消息，Shift+Enter 换行"
              disabled={loading}
              rows={1}
            />
            <button type="submit" className="send-btn" disabled={!canSend}>
              {loading ? (
                <span className="typing small">
                  <i />
                  <i />
                  <i />
                </span>
              ) : (
                "发送"
              )}
            </button>
          </div>
          <div className="composer-hint">
            <span>Enter 发送 · Shift+Enter 换行</span>
            <span>{input.length} 字</span>
          </div>
        </form>
      </main>

      <aside className="inspector">
        <div className="inspector-head">
          <div>
            <h2>执行观察台</h2>
            <span>Plan & Activity</span>
          </div>
        </div>

        <section className="plan-card">
          <div className="plan-head">
            <span>任务计划</span>
            <small>{effectivePlanItems.length} 项</small>
          </div>
          <div className="plan-stats">
            <span className="stat state-in_progress">
              执行中 {planStats.in_progress}
            </span>
            <span className="stat state-pending">
              待开始 {planStats.pending}
            </span>
            <span className="stat state-completed">
              完成 {planStats.completed}
            </span>
            <span className="stat state-failed">失败 {planStats.failed}</span>
          </div>
          <ol className="plan-list">
            {effectivePlanItems.map((item) => (
              <PlanRow key={item.task_id} item={item} />
            ))}
            {effectivePlanItems.length === 0 ? (
              <li className="plan-empty">
                {activeIncident
                  ? "Worker 已启动，等待更多执行快照落盘。"
                  : "还没有计划。发送一个任务描述后，主 Agent 会在这里生成执行清单。"}
              </li>
            ) : null}
          </ol>
        </section>

        <section className="trace-card">
          <div className="plan-head">
            <span>执行日志</span>
            <small>{effectiveActivityLog.length} 条</small>
          </div>
          <ul className="activity-list">
            {effectiveActivityLog
              .slice()
              .reverse()
              .map((entry) => (
                <ActivityLogRow key={entry.entry_id} entry={entry} />
              ))}
            {effectiveActivityLog.length === 0 ? (
              <li className="plan-empty">
                {activeIncident
                  ? "Incident 已识别，等待 Worker 回传更详细的执行日志。"
                  : "暂无执行日志"}
              </li>
            ) : null}
          </ul>
        </section>

        <section className="trace-card">
          <div className="plan-head">
            <span>运行态</span>
            <small>{agentHealth?.incident_total ?? incidents.length} 个 incident</small>
          </div>
          <ul className="activity-list">
            <ActivityLogRow
              entry={{
                entry_id: "runtime-ingest",
                kind: agentHealth?.ingest_enabled ? "success" : "error",
                message: agentHealth?.ingest_enabled
                  ? "日志监听已开启"
                  : "日志监听未开启",
                created_at: new Date().toISOString(),
              }}
            />
            <ActivityLogRow
              entry={{
                entry_id: "runtime-planner",
                kind:
                  agentHealth?.planner_active === "idle" ? "info" : "warning",
                message: `Planner 状态：${agentHealth?.planner_active ?? "unknown"}`,
                created_at: new Date().toISOString(),
              }}
            />
          </ul>
        </section>
      </aside>
    </div>
  );
}

function PlanRow({ item }: { item: PlanItem }) {
  const [open, setOpen] = useState(false);
  const hasBody = Boolean(item.details || item.response);
  return (
    <li className={`plan-item state-${item.status}`}>
      <button
        type="button"
        className="plan-row"
        onClick={() => hasBody && setOpen((v) => !v)}
      >
        <span className={`plan-check state-${item.status}`} aria-hidden>
          {item.status === "completed"
            ? "✓"
            : item.status === "failed"
              ? "!"
              : item.status === "in_progress"
                ? "•"
                : ""}
        </span>
        <div className="plan-main">
          <div className="plan-title">{item.content || item.task_id}</div>
          <div className="plan-meta">
            <span className={`plan-pill state-${item.status}`}>
              {STATUS_LABELS[item.status]}
            </span>
            <span className="plan-assignee">
              {AGENT_LABELS[item.assignee] ?? item.assignee}
            </span>
            <span className="plan-id">{item.task_id}</span>
          </div>
        </div>
        {hasBody ? (
          <span className={`plan-arrow${open ? " open" : ""}`}>›</span>
        ) : null}
      </button>
      {hasBody && open ? (
        <div className="plan-body">
          {item.details ? (
            <section className="plan-section">
              <div className="plan-section-label">任务说明</div>
              <pre className="plan-details">{item.details}</pre>
            </section>
          ) : null}
          {item.response ? (
            <section className="plan-section">
              <div className="plan-section-label">执行结果</div>
              <pre className="plan-details plan-response">{item.response}</pre>
            </section>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function ActivityLogRow({ entry }: { entry: ActivityLogEntry }) {
  return (
    <li className={`activity-item kind-${entry.kind}`}>
      <span className={`activity-dot kind-${entry.kind}`} aria-hidden />
      <span className="activity-time">{formatDateTime(entry.created_at)}</span>
      <span className="activity-message" title={entry.message}>
        {entry.message}
      </span>
    </li>
  );
}
