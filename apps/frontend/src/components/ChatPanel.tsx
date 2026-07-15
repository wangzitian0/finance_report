"use client";

import type { KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquareText, PanelLeft } from "lucide-react";

import { apiFetch, apiStream, apiDelete } from "@/lib/api";
import { fetchAiModels } from "@/lib/aiModels";
import type { Schemas } from "@/lib/api-schema";
import type {
  AdvisorSuggestion,
  ChatActionChip,
  ChatCitation,
  ChatResponseMetadata,
  ChatSuggestionsResponse,
} from "@/lib/types";
import { AdvisorBrief, safeAdvisorHref } from "@/components/advisor/AdvisorBrief";
import Sheet from "@/components/ui/Sheet";

const DISCLAIMER_EN = "The above analysis is for reference only.";
const DISCLAIMER_ZH = "\u4ee5\u4e0a\u5206\u6790\u4ec5\u4f9b\u53c2\u8003\u3002";
const SESSION_KEY = "ai_chat_session_id";
const MODEL_KEY = "ai_chat_model_v1";

type ChatRole = "user" | "assistant";
interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  citations?: ChatCitation[];
  actions?: ChatActionChip[];
}
type ChatSessionResponse = Schemas["ChatSessionResponse"];
type ChatHistoryResponse = Schemas["ChatHistoryResponse"];
interface ChatPanelProps { variant?: "page" | "widget"; initialPrompt?: string | null; onClose?: () => void; }

const getBrowserLanguage = () => typeof window === "undefined" ? "en" : navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
const splitDisclaimer = (content: string) => {
  if (content.trim().endsWith(DISCLAIMER_EN)) return { body: content.replace(DISCLAIMER_EN, "").trim(), disclaimer: DISCLAIMER_EN };
  if (content.trim().endsWith(DISCLAIMER_ZH)) return { body: content.replace(DISCLAIMER_ZH, "").trim(), disclaimer: DISCLAIMER_ZH };
  return { body: content, disclaimer: "" };
};
const formatErrorMessage = (error: unknown) => error instanceof Error ? error.message : "Unable to send the message.";
const parseChatMetadata = (response: Response): Pick<ChatMessage, "citations" | "actions"> | undefined => {
  const headers = response.headers as Headers | undefined;
  const raw = typeof headers?.get === "function" ? headers.get("X-Advisor-Metadata") : null;
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as Partial<ChatResponseMetadata>;
    const citations = Array.isArray(parsed.citations)
      ? parsed.citations.filter(
          (citation): citation is ChatCitation =>
            typeof citation?.label === "string" &&
            typeof citation?.source_ref === "string" &&
            typeof citation?.confidence_tier === "string" &&
            typeof citation?.href === "string",
        )
      : [];
    const actions = Array.isArray(parsed.actions)
      ? parsed.actions.filter(
          (action): action is ChatActionChip =>
            typeof action?.kind === "string" &&
            typeof action?.label === "string" &&
            typeof action?.href === "string",
        )
      : [];
    return citations.length || actions.length ? { citations, actions } : undefined;
  } catch {
    return undefined;
  }
};

export default function ChatPanel({ variant = "page", initialPrompt, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [advisorSuggestions, setAdvisorSuggestions] = useState<AdvisorSuggestion[]>([]);
  const [chatSessions, setChatSessions] = useState<ChatSessionResponse[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [initialPromptHandled, setInitialPromptHandled] = useState(false);
  const [models, setModels] = useState<{ id: string; name?: string; is_free: boolean }[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [loadingModels, setLoadingModels] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const language = useMemo(() => getBrowserLanguage(), []);

  const scrollToBottom = useCallback(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, []);

  const fetchSuggestions = useCallback(async () => {
    try {
      const data = await apiFetch<ChatSuggestionsResponse>(
        `/api/chat/suggestions?language=${language}&include_structured=true`,
      );
      setSuggestions(data.suggestions || []);
      setAdvisorSuggestions(data.structured_suggestions || []);
    } catch {
      setSuggestions([]);
      setAdvisorSuggestions([]);
    }
  }, [language]);

  const refreshSessionList = useCallback(async () => {
    const data = await apiFetch<ChatHistoryResponse>("/api/chat/history?limit=50");
    setChatSessions(data.sessions || []);
    return data.sessions || [];
  }, []);

  const loadSession = useCallback(async (nextSessionId: string) => {
    setLoadingHistory(true);
    try {
      const data = await apiFetch<ChatHistoryResponse>(`/api/chat/history?session_id=${nextSessionId}`);
      const session = data.sessions[0];
      if (session) {
        setSessionId(session.id);
        // Persisted history may include a "system" role (prompt/context
        // messages); only user/assistant turns render as chat bubbles.
        setMessages(
          (session.messages ?? [])
            .filter((m): m is typeof m & { role: ChatRole } => m.role === "user" || m.role === "assistant")
            .map((m) => ({ id: m.id, role: m.role, content: m.content })),
        );
        localStorage.setItem(SESSION_KEY, session.id);
      }
    } catch {
      localStorage.removeItem(SESSION_KEY);
      setSessionId(null);
      setMessages([]);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    const storedSession = typeof window !== "undefined" ? localStorage.getItem(SESSION_KEY) : null;
    try {
      const sessions = await refreshSessionList();
      const selectedSession = storedSession && sessions.some((session) => session.id === storedSession)
        ? storedSession
        : sessions[0]?.id;
      if (selectedSession) {
        await loadSession(selectedSession);
      } else {
        setLoadingHistory(false);
      }
    } catch {
      if (storedSession) {
        await loadSession(storedSession);
      } else {
        setLoadingHistory(false);
      }
    }
  }, [loadSession, refreshSessionList]);

  useEffect(() => { fetchSuggestions(); loadHistory(); }, [fetchSuggestions, loadHistory]);
  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);
  useEffect(() => {
    let active = true;
    const loadModels = async () => {
      try {
        const data = await fetchAiModels({ modality: "text" });
        if (!active) return;
        setModels(data.models);
        const stored = typeof window !== "undefined" ? localStorage.getItem(MODEL_KEY) : null;
        let preferred = stored && data.models.some((m) => m.id === stored) ? stored : data.default_model;
        if (!data.models.some((m) => m.id === preferred)) {
          preferred = data.models[0]?.id || "";
        }
        setSelectedModel(preferred);
      } catch {
        if (!active) return;
        setModels([]);
        setSelectedModel("");
      } finally {
        if (active) setLoadingModels(false);
      }
    };
    void loadModels();
    return () => {
      active = false;
    };
  }, []);

  const updateMessage = useCallback((
    id: string,
    content: string,
    streaming?: boolean,
    metadata?: Pick<ChatMessage, "citations" | "actions">,
  ) => {
    setMessages((prev) =>
      prev.map((i) => (i.id === id ? { ...i, content, streaming, ...(metadata ?? {}) } : i)),
    );
  }, []);

  const handleStream = useCallback(async (
    response: Response,
    assistantId: string,
    metadata?: Pick<ChatMessage, "citations" | "actions">,
  ) => {
    const reader = response.body?.getReader();
    if (!reader) {
      updateMessage(assistantId, "No response stream available.", false, metadata);
      return;
    }
    const decoder = new TextDecoder();
    let aggregated = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      if (value) {
        const decodedChunk = decoder.decode(value, { stream: true });
        aggregated += decodedChunk;
        updateMessage(assistantId, aggregated, true, metadata);
      }
    }
    aggregated += decoder.decode();
    updateMessage(assistantId, aggregated, false, metadata);
  }, [updateMessage]);

  const sendMessage = useCallback(async (text?: string) => {
    const messageText = (text ?? input).trim();
    if (!messageText || isStreaming) return;
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: "user", content: messageText };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = { id: assistantId, role: "assistant", content: "", streaming: true };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setIsStreaming(true);
    setError(null);
    try {
      const { response: res, sessionId: newSessionId } = await apiStream("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
          model: selectedModel || undefined,
        }),
      });
      if (newSessionId) {
        setSessionId(newSessionId);
        localStorage.setItem(SESSION_KEY, newSessionId);
      }
      const metadata = parseChatMetadata(res);
      if (metadata) updateMessage(assistantId, "", true, metadata);
      await handleStream(res, assistantId, metadata);
      void refreshSessionList();
      setIsStreaming(false);
    } catch (err) {
      setError(formatErrorMessage(err));
      updateMessage(assistantId, formatErrorMessage(err), false);
      setIsStreaming(false);
    }
  }, [handleStream, input, isStreaming, refreshSessionList, selectedModel, sessionId, updateMessage]);

  useEffect(() => {
    if (initialPromptHandled || !initialPrompt || loadingHistory) return;
    if (messages.length > 0) { setInput(initialPrompt); setInitialPromptHandled(true); return; }
    setInitialPromptHandled(true);
    void sendMessage(initialPrompt);
  }, [initialPrompt, initialPromptHandled, loadingHistory, messages.length, sendMessage]);

  const clearSession = async () => {
    if (sessionId) {
      try {
        await apiDelete(`/api/chat/session/${sessionId}`);
      } catch {
        // Session deletion is best-effort; ignore network errors
      }
    }
    localStorage.removeItem(SESSION_KEY);
    setSessionId(null);
    setMessages([]);
    void refreshSessionList();
  };

  const sessionTitle = (session: ChatSessionResponse) => session.title || session.last_message?.content || "Untitled session";

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); } };

  return (
    <div className={variant === "widget" ? "flex h-full flex-col" : "flex h-full min-h-[540px] flex-col"}>
      <div className={variant === "widget" ? "flex items-center justify-between border-b border-[var(--border)] pb-3" : "flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-4"}>
        <div>
          <p className="text-xs text-[var(--accent)] uppercase tracking-wide">AI</p>
          <h2 className="text-lg font-semibold">Conversation</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSessionsOpen(true)}
            className="btn-secondary inline-flex items-center gap-1.5 px-3 py-1 text-xs"
          >
            <PanelLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Sessions
          </button>
          <select
            className="input text-xs min-w-[220px]"
            value={selectedModel}
            onChange={(event) => {
              const next = event.target.value;
              setSelectedModel(next);
              if (typeof window !== "undefined" && next) {
                localStorage.setItem(MODEL_KEY, next);
              }
            }}
            disabled={loadingModels}
            aria-label="AI model"
          >
            {models.length === 0 ? (
              <option value="">Default (server)</option>
            ) : (
              models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name || model.id} — {model.is_free ? "Free" : "Paid"}
                </option>
              ))
            )}
          </select>
          <button onClick={clearSession} className="btn-secondary text-xs px-3 py-1">New</button>
          {onClose && <button onClick={onClose} className="btn-secondary text-xs px-3 py-1">Close</button>}
        </div>
      </div>

      <Sheet isOpen={sessionsOpen} onClose={() => setSessionsOpen(false)} title="AI sessions" width="max-w-sm">
        <div className="space-y-2">
          {chatSessions.length === 0 && (
            <div className="rounded-md border border-dashed border-[var(--border)] p-4 text-sm text-muted">
              No saved conversations yet.
            </div>
          )}
          {chatSessions.map((session) => (
            <button
              type="button"
              key={session.id}
              onClick={() => {
                setSessionsOpen(false);
                void loadSession(session.id);
              }}
              className={`w-full rounded-md border p-3 text-left text-sm transition-colors ${
                session.id === sessionId
                  ? "border-[var(--accent)] bg-[var(--accent-muted)]"
                  : "border-[var(--border)] bg-[var(--background-card)] hover:bg-[var(--background-muted)]"
              }`}
            >
              <div className="flex items-center gap-2">
                <MessageSquareText className="h-4 w-4 text-muted" aria-hidden="true" />
                <span className="min-w-0 truncate font-medium">{sessionTitle(session)}</span>
              </div>
              <p className="mt-1 text-xs text-muted">
                {session.message_count ?? session.messages?.length ?? 0} messages
              </p>
            </button>
          ))}
        </div>
      </Sheet>

      {suggestions.length > 0 && variant === "page" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {suggestions.map((s) => <button key={s} onClick={() => void sendMessage(s)} className="badge badge-muted hover:bg-[var(--accent-muted)] hover:text-[var(--accent)] transition-colors cursor-pointer">{s}</button>)}
        </div>
      )}

      {advisorSuggestions.length > 0 && variant === "page" && (
        <AdvisorBrief suggestions={advisorSuggestions} compact className="mt-4" />
      )}

      {error && <div className="mt-4 alert-error">{error}</div>}

      <div ref={scrollRef} aria-live="polite" className={variant === "widget" ? "mt-4 flex-1 space-y-3 overflow-y-auto pr-2" : "mt-6 flex-1 space-y-4 overflow-y-auto pr-2"}>
        {loadingHistory && <div className="text-sm text-muted">Loading chat history...</div>}
        {!loadingHistory && messages.length === 0 && <div className="p-8 rounded-md border border-dashed border-[var(--border)] text-center text-sm text-muted">Ask a question about your reports, budgets, or reconciliation health.</div>}
        {messages.map((m) => {
          const { body, disclaimer } = splitDisclaimer(m.content);
          const isAssistant = m.role === "assistant";
          const citations = isAssistant
            ? (m.citations ?? [])
                .map((citation) => ({ ...citation, href: safeAdvisorHref(citation.href) }))
                .filter((citation) => citation.href !== "/")
            : [];
          const actions = isAssistant
            ? (m.actions ?? [])
                .map((action) => ({ ...action, href: safeAdvisorHref(action.href) }))
                .filter((action) => action.href !== "/")
            : [];
          return (
            <div key={m.id} className={isAssistant ? "p-4 rounded-md bg-[var(--background-muted)]" : "p-4 rounded-md bg-[var(--accent)] text-white"}>
              <p className="text-sm">{body}</p>
              {m.streaming && <span className="mt-2 inline-block text-xs text-[var(--accent)]">Streaming...</span>}
              {isAssistant && disclaimer && <p className="mt-2 text-[10px] text-muted uppercase tracking-wide">{disclaimer}</p>}
              {isAssistant && (citations.length > 0 || actions.length > 0) && (
                <div className="mt-3 flex flex-col gap-2">
                  {citations.length > 0 && (
                    <div className="flex flex-wrap gap-2" aria-label="Answer citations">
                      {citations.map((citation) => (
                        <a
                          key={`${citation.source_ref}-${citation.href}`}
                          href={citation.href}
                          className="badge badge-info"
                        >
                          <span>{citation.label}</span>
                          <span className="ml-1 font-mono">{citation.confidence_tier}</span>
                        </a>
                      ))}
                    </div>
                  )}
                  {actions.length > 0 && (
                    <div className="flex flex-wrap gap-2" aria-label="Answer actions">
                      {actions.map((action) => (
                        <a key={`${action.kind}-${action.href}`} href={action.href} className="btn-secondary text-xs">
                          {action.label}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-4 p-3 rounded-md bg-[var(--background-muted)]">
        <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown} rows={variant === "widget" ? 2 : 3} placeholder="Ask about spending trends, reports, or reconciliation..." className="w-full resize-none bg-transparent text-sm outline-none" />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[10px] text-muted">Enter to send, Shift+Enter for newline</span>
          <button onClick={() => void sendMessage()} disabled={isStreaming || !input.trim()} className="btn-primary text-xs px-4 py-1.5">{isStreaming ? "Sending" : "Send"}</button>
        </div>
      </div>
    </div>
  );
}
