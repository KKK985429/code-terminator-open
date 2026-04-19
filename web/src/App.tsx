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
  fetchAgentStatus,
  fetchConversation,
  fetchConversations,
  fetchPlanSnapshot,
  fetchRuntimeSettings,
  saveRuntimeSettings,
  sendMessageStream,
} from "./api";
import type {
  AgentStatus,
  ActivityLogEntry,
  ChatMessage,
  ConversationSummary,
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
  "帮我给这个仓库生成发版与变更日志流程",
  "给我规划一下从 0 到 1 搭建 CI/CD 的任务列表",
  "对现有代码做一次架构梳理，输出重构计划",
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

export function App() {
  const [agentStatus, setAgentStatus] = useState<AgentStatus[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [planSnapshot, setPlanSnapshot] = useState<PlanSnapshotResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null);
  const [githubTokenDraft, setGithubTokenDraft] = useState("");
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

  const refreshConversations = useCallback(async () => {
    const [statusResp, conversationResp] = await Promise.all([
      fetchAgentStatus(),
      fetchConversations(),
    ]);
    setAgentStatus(statusResp.roles);
    setConversations(conversationResp.conversations);
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
    void refreshConversations().catch((err: Error) => setError(err.message));
    void fetchRuntimeSettings()
      .then((settings) => {
        setRuntimeSettings(settings);
        setGithubTokenDraft(settings.github_token);
      })
      .catch((err: Error) => {
        logBackgroundError("fetchRuntimeSettings", err);
      });
    const timer = window.setInterval(() => {
      void refreshConversations().catch((err: Error) => {
        logBackgroundError("refreshConversations", err);
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [logBackgroundError, refreshConversations]);

  useEffect(() => {
    if (!activeConversationId && conversations.length > 0) {
      setActiveConversationId(conversations[0].conversation_id);
    }
  }, [activeConversationId, conversations]);

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

  // Periodically refresh plan snapshot for active conversation so hook-triggered
  // changes (subagent completion) can show up without a new user message.
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
    ? githubTokenDraft !== runtimeSettings.github_token
    : githubTokenDraft.length > 0;

  const planItems = planSnapshot?.plan_items ?? [];
  const activityLog = planSnapshot?.activity_log ?? [];

  const planStats = useMemo(() => {
    const counts: Record<PlanStatus, number> = {
      pending: 0,
      in_progress: 0,
      completed: 0,
      failed: 0,
    };
    for (const item of planItems) counts[item.status] += 1;
    return counts;
  }, [planItems]);

  const displayedAgents = useMemo(() => {
    return agentStatus.filter(
      (item) => item.role === "leader" || item.active_count > 0 || item.busy_count > 0,
    );
  }, [agentStatus]);

  function startNewConversation() {
    setActiveConversationId("");
    setMessages([]);
    setPlanSnapshot(null);
    setInput("");
    textareaRef.current?.focus();
  }

  async function persistGithubToken(): Promise<void> {
    setSavingToken(true);
    setTokenStatus("");
    try {
      const saved = await saveRuntimeSettings(githubTokenDraft);
      setRuntimeSettings(saved);
      setGithubTokenDraft(saved.github_token);
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
        await refreshConversations();
      } catch (err) {
        if (!receivedDone) {
          throw err;
        }
        logBackgroundError("post-send refreshConversations", err);
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
          <span className="plus">+</span> 新建对话
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
                    onClick={() =>
                      setActiveConversationId(conversation.conversation_id)
                    }
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
            <div className="main-title">
              {activeConversationId
                ? conversationTitle(
                    conversations.find(
                      (c) => c.conversation_id === activeConversationId,
                    ) ?? {
                      conversation_id: activeConversationId,
                      thread_id: "",
                      message_count: 0,
                      updated_at: "",
                    },
                  )
                : "新对话"}
            </div>
            <div className="main-subtitle">
              {activeConversationId
                ? `thread · ${activeConversationId}`
                : "发送第一条消息以开始"}
            </div>
          </div>
          <div className="main-actions">
            <span className={`status-dot ${loading ? "busy" : "idle"}`} />
            <span className="status-text">
              {loading ? "主 Agent 工作中…" : "就绪"}
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
            <strong>GitHub Token</strong>
            <span>
              worker 默认鉴权走本地运行时配置，不再读取环境变量。
            </span>
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
              {savingToken ? "保存中…" : "保存"}
            </button>
          </div>
          <div className="runtime-settings-hint">
            {tokenStatus ||
              (runtimeSettings?.updated_at
                ? `上次更新 ${formatDateTime(runtimeSettings.updated_at)}`
                : "保存后会立刻作为后端 worker 的默认 GitHub 鉴权。")}
          </div>
        </section>

        <section className="chat-feed" aria-live="polite">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <h2>你好，我是 Code Terminator 的主 Agent</h2>
              <p>
                告诉我你想完成什么，我会拆解成任务计划、调度 worker 与 reviewer，并把每一步写在右侧的执行台上。
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
              placeholder="给主 Agent 发消息… Shift+Enter 换行"
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
            <span>按 Enter 发送 · Shift+Enter 换行</span>
            <span>{input.length} 字</span>
          </div>
        </form>
      </main>

      <aside className="inspector">
        <div className="inspector-head">
          <h2>执行观察台</h2>
        </div>

        <section className="plan-card">
          <div className="plan-head">
            <span>任务计划</span>
            <small>{planItems.length} 项</small>
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
            {planItems.map((item) => (
              <PlanRow key={item.task_id} item={item} />
            ))}
            {planItems.length === 0 ? (
              <li className="plan-empty">
                还没有计划。发送一个任务描述，主 Agent 会在这里生成 list。
              </li>
            ) : null}
          </ol>
        </section>

        <section className="trace-card">
          <div className="plan-head">
            <span>执行日志</span>
            <small>{activityLog.length} 条</small>
          </div>
          <ul className="activity-list">
            {activityLog
              .slice()
              .reverse()
              .map((entry) => (
                <ActivityLogRow key={entry.entry_id} entry={entry} />
              ))}
            {activityLog.length === 0 ? (
              <li className="plan-empty">暂无执行日志</li>
            ) : null}
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
                ? "▶"
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
