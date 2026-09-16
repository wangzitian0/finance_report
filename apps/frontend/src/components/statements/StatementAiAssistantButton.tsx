"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, MessageSquare } from "lucide-react";
import type { MoneyValue } from "@/lib/types";

export interface StatementContext {
  id?: string;
  filename?: string;
  institution?: string;
  currency?: string;
  periodStart?: string | null;
  periodEnd?: string | null;
  transactionCount?: number;
}

export interface TransactionContext {
  id?: string;
  description?: string;
  amount?: MoneyValue;
  currency?: string;
  date?: string;
}

export interface StatementAiAssistantButtonProps {
  statement?: StatementContext;
  transaction?: TransactionContext;
  className?: string;
  label?: string;
  variant?: "primary" | "secondary" | "ghost";
  icon?: "sparkles" | "message";
  onNavigate?: (prompt: string) => void;
}

export function buildTransactionChatPrompt(t: TransactionContext): string {
  const desc = t.description?.trim() || "Untitled Transaction";
  const amt = t.amount !== undefined && t.amount !== null ? String(t.amount) : "N/A";
  const curr = t.currency?.trim() ? ` ${t.currency.trim()}` : "";
  const dt = t.date?.trim() || "unspecified date";
  return `Please analyze this transaction: '${desc}', amount: ${amt}${curr} on ${dt}. What is the recommended accounting category and is it tax deductible?`;
}

export function buildStatementChatPrompt(s: StatementContext): string {
  const file = s.filename?.trim() || "Untitled Statement";
  const inst = s.institution?.trim() || "Unknown Institution";
  const period =
    s.periodStart && s.periodEnd
      ? `${s.periodStart} to ${s.periodEnd}`
      : s.periodStart || s.periodEnd || "unspecified period";
  const count =
    typeof s.transactionCount === "number"
      ? String(s.transactionCount)
      : "an unknown number of";
  return `Please review this statement: '${file}' (${inst}, ${period}) with ${count} transactions. Highlight major expense categories and any potential anomalies.`;
}

export function StatementAiAssistantButton({
  statement,
  transaction,
  className = "",
  label,
  variant = "secondary",
  icon = "sparkles",
  onNavigate,
}: StatementAiAssistantButtonProps) {
  const router = useRouter();

  const prompt = useMemo(() => {
    if (transaction) return buildTransactionChatPrompt(transaction);
    if (statement) return buildStatementChatPrompt(statement);
    return null;
  }, [statement, transaction]);

  const defaultLabel = transaction ? "Ask AI about transaction" : "Ask AI Assistant";
  const buttonText = label || defaultLabel;

  const handleClick = () => {
    if (!prompt) return;
    if (onNavigate) {
      onNavigate(prompt);
      return;
    }
    try {
      sessionStorage.setItem("ai_chat_pending_prompt", prompt);
    } catch {
      // ignore storage error
    }
    router.push("/chat");
  };

  const variantClass =
    variant === "primary"
      ? "btn-primary"
      : variant === "ghost"
        ? "btn-ghost text-[var(--accent)]"
        : "btn-secondary";

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={!prompt}
      className={`inline-flex items-center gap-1.5 text-xs font-medium ${variantClass} ${className} disabled:opacity-40 disabled:cursor-not-allowed`}
      title={prompt || "No context provided"}
      aria-label={buttonText}
      data-testid="statement-ai-assistant-button"
    >
      {icon === "sparkles" ? (
        <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" aria-hidden="true" />
      ) : (
        <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      <span>{buttonText}</span>
    </button>
  );
}
