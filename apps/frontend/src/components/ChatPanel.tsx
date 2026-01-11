"use client";

import type { KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_URL } from "@/lib/api";

const DISCLAIMER_EN = "The above analysis is for reference only.";
const DISCLAIMER_ZH = "\u4ee5\u4e0a\u5206\u6790\u4ec5\u4f9b\u53c2\u8003\u3002";

const SESSION_KEY = "ai_chat_session_id";

type ChatRole = "user" | "assistant";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
}

interface ChatMessageResponse {
  id: string;
  role: ChatRole;
  content: string;
}

interface ChatSessionResponse {
  id: string;
  messages: ChatMessageResponse[];
}

interface ChatHistoryResponse {
  sessions: ChatSessionResponse[];
}

interface ChatSuggestionsResponse {
  suggestions: string[];
}

interface ChatPanelProps {
  variant?: "page" | "widget";
  initialPrompt?: string | null;
  onClose?: () => void;
}

const getBrowserLanguage = () => {
  if (typeof window === "undefined") return "en";
  const lang = navigator.language.toLowerCase();
  return lang.startsWith("zh") ? "zh" : "en";
};

const splitDisclaimer = (content: string) => {
  if (content.trim().endsWith(DISCLAIMER_EN)) {
    return {
      body: content.replace(DISCLAIMER_EN, "").trim(),
      disclaimer: DISCLAIMER_EN,
    };
  }
  if (content.trim().endsWith(DISCLAIMER_ZH)) {
    return {
      body: content.replace(DISCLAIMER_ZH, "").trim(),
      disclaimer: DISCLAIMER_ZH,
    };
  }
  return { body: content, disclaimer: "" };
};

const formatErrorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Unable to send the message.";

export default function ChatPanel({ variant = "page", initialPrompt, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [initialPromptHandled, setInitialPromptHandled] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const language = useMemo(() => getBrowserLanguage(), []);

  const scrollToBottom = useCallback(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, []);

  const fetchSuggestions = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/chat/suggestions?language=${language}`);
      if (!res.ok) return;
      const data = (await res.json()) as ChatSuggestionsResponse;
      setSuggestions(data.suggestions || []);
    } catch {
      setSuggestions([]);
    }
  }, [language]);

  const loadHistory = useCallback(async () => {
    const storedSession = typeof window !== "undefined" ? localStorage.getItem(SESSION_KEY) : null;
    if (!storedSession) {
      setLoadingHistory(false);
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/chat/history?session_id=${storedSession}`);
      if (!res.ok) {
        localStorage.removeItem(SESSION_KEY);
        setLoadingHistory(false);
        return;
      }
      const data = (await res.json()) as ChatHistoryResponse;
      const session = data.sessions[0];
      if (session) {
        setSessionId(session.id);
        setMessages(
          session.messages.map((msg) => ({
            id: msg.id,
            role: msg.role,
            content: msg.content,
          }))
        );
      }
    } catch {
      localStorage.removeItem(SESSION_KEY);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    fetchSuggestions();
    loadHistory();
  }, [fetchSuggestions, loadHistory]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (initialPromptHandled) return;
    if (!initialPrompt || loadingHistory) return;
    if (messages.length > 0) {
      setInput(initialPrompt);
      setInitialPromptHandled(true);
      return;
    }
    setInitialPromptHandled(true);
    void sendMessage(initialPrompt);
  }, [initialPrompt, initialPromptHandled, loadingHistory, messages.length]);

  const updateMessage = (id: string, content: string, streaming?: boolean) => {
    setMessages((prev) =>
      prev.map((item) => (item.id === id ? { ...item, content, streaming } : item))
    );
  };

  const handleStream = async (response: Response, assistantId: string) => {
    const reader = response.body?.getReader();
    if (!reader) {
      updateMessage(assistantId, "No response stream available.");
      return;
    }

    const decoder = new TextDecoder();
    let aggregated = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) {
        aggregated += decoder.decode(value, { stream: true });
        updateMessage(assistantId, aggregated, true);
      }
    }

    aggregated += decoder.decode();
    updateMessage(assistantId, aggregated, false);
  };

  const sendMessage = async (text?: string) => {
    const messageText = (text ?? input).trim();
    if (!messageText || isStreaming) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: messageText,
    };

    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setIsStreaming(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
        }),
      });

      if (!res.ok) {
        const detailText = await res.text();
        let detail = detailText || "AI service is unavailable.";
        try {
          const parsed = JSON.parse(detailText) as { detail?: string };
          if (parsed.detail) {
            detail = parsed.detail;
          }
        } catch {
          // Ignore JSON parse errors.
        }
        updateMessage(assistantId, detail, false);
        setError(detail);
        setIsStreaming(false);
        return;
      }

      const newSessionId = res.headers.get("X-Session-Id") || sessionId;
      if (newSessionId) {
        setSessionId(newSessionId);
        localStorage.setItem(SESSION_KEY, newSessionId);
      }

      await handleStream(res, assistantId);
      setIsStreaming(false);
    } catch (err) {
      setError(formatErrorMessage(err));
      updateMessage(assistantId, formatErrorMessage(err), false);
      setIsStreaming(false);
    }
  };

  const clearSession = async () => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    try {
      await fetch(`${API_URL}/api/chat/session/${sessionId}`, { method: "DELETE" });
    } catch {
      // Ignore deletion errors, still clear locally.
    }
    localStorage.removeItem(SESSION_KEY);
    setSessionId(null);
    setMessages([]);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  const wrapperClasses =
    variant === "widget"
      ? "flex h-full flex-col"
      : "flex h-full min-h-[540px] flex-col";

  return (
    <div className={wrapperClasses}>
      <div
        className={
          variant === "widget"
            ? "flex items-center justify-between border-b border-white/40 pb-3"
            : "flex flex-wrap items-center justify-between gap-3 border-b border-white/40 pb-4"
        }
      >
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-amber-700">AI Advisor</p>
          <h2 className="text-xl font-semibold text-[#13201b]">Financial Insight Console</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={clearSession}
            className="rounded-full border border-amber-200 px-3 py-1 text-xs uppercase tracking-[0.2em] text-amber-700"
          >
            Clear session
          </button>
          {onClose ? (
            <button
              onClick={onClose}
              className="rounded-full border border-slate-200 px-3 py-1 text-xs uppercase tracking-[0.2em] text-slate-500"
            >
              Close
            </button>
          ) : null}
        </div>
      </div>

      {suggestions.length > 0 && variant === "page" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              onClick={() => void sendMessage(suggestion)}
              className="rounded-full border border-emerald-200 bg-white/80 px-4 py-2 text-xs text-emerald-700 transition hover:bg-emerald-50"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      <div
        ref={scrollRef}
        className={
          variant === "widget"
            ? "mt-4 flex-1 space-y-3 overflow-y-auto pr-2"
            : "mt-6 flex-1 space-y-4 overflow-y-auto pr-2"
        }
      >
        {loadingHistory ? (
          <div className="text-sm text-slate-500">Loading chat history...</div>
        ) : null}
        {!loadingHistory && messages.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-emerald-100 bg-white/70 px-6 py-10 text-center text-sm text-slate-500">
            Ask a question about your reports, budgets, or reconciliation health.
          </div>
        ) : null}
        {messages.map((message) => {
          const { body, disclaimer } = splitDisclaimer(message.content);
          const isAssistant = message.role === "assistant";
          return (
            <div
              key={message.id}
              className={
                isAssistant
                  ? "rounded-3xl border border-white/60 bg-white/80 px-5 py-4 shadow-sm"
                  : "rounded-3xl bg-[#0f766e] px-5 py-4 text-white shadow-lg"
              }
            >
              <p className={isAssistant ? "text-sm text-slate-700" : "text-sm"}>{body}</p>
              {message.streaming && (
                <span className="mt-2 inline-block text-xs uppercase tracking-[0.2em] text-emerald-500">
                  Streaming...
                </span>
              )}
              {isAssistant && disclaimer ? (
                <p className="mt-3 text-[11px] uppercase tracking-[0.2em] text-amber-700">
                  {disclaimer}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="mt-5 rounded-3xl border border-white/40 bg-white/80 p-4 shadow-sm">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={variant === "widget" ? 2 : 3}
          placeholder="Ask about spending trends, reports, or reconciliation..."
          className="w-full resize-none bg-transparent text-sm text-slate-700 outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div className="text-[11px] text-slate-400">
            Enter to send, Shift+Enter for newline
          </div>
          <button
            onClick={() => void sendMessage()}
            disabled={isStreaming || !input.trim()}
            className="rounded-full bg-emerald-600 px-5 py-2 text-xs uppercase tracking-[0.25em] text-white shadow-md shadow-emerald-200/60 transition hover:bg-emerald-700 disabled:opacity-50"
          >
            {isStreaming ? "Sending" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
