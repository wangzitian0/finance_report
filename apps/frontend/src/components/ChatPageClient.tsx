"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import ChatPanel from "@/components/ChatPanel";

export const CONSENT_KEY = "ai_advisor_disclaimer_v1";

export const PENDING_CHAT_PROMPT_KEY = "ai_chat_pending_prompt";

export default function ChatPageClient() {
  const searchParams = useSearchParams();
  const [sessionPrompt] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const stored = sessionStorage.getItem(PENDING_CHAT_PROMPT_KEY);
      if (stored) {
        sessionStorage.removeItem(PENDING_CHAT_PROMPT_KEY);
        return stored;
      }
    } catch {
      // ignore storage errors
    }
    return null;
  });
  const initialPrompt = sessionPrompt || searchParams.get("prompt");
  const [consentGiven, setConsentGiven] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(CONSENT_KEY) === "accepted";
  });

  const acceptConsent = () => {
    localStorage.setItem(CONSENT_KEY, "accepted");
    setConsentGiven(true);
  };

  return (
    <div className="p-4 sm:p-6 max-w-full overflow-hidden">
      <div className="page-header flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="page-title">AI Advisor</h1>
          <p className="page-description">
            Ask about spending trends, report highlights, or reconciliation health. Read-only guidance based on posted data.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/" className="btn-secondary text-sm">Home</Link>
          <Link href="/reports/balance-sheet" className="btn-secondary text-sm">Reports</Link>
        </div>
      </div>

      {!consentGiven && (
        <div role="region" aria-label="Disclaimer" className="mt-4 p-4 rounded-lg bg-surface-raised border border-border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fade-in">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Disclaimer</h2>
            <p className="text-xs text-muted mt-0.5">
              This AI financial advisor provides guidance based on your posted financial data. It
              may contain errors and does not constitute professional financial advice. Please
              consult a licensed advisor before making major decisions.
            </p>
          </div>
          <button onClick={acceptConsent} className="btn-primary text-xs shrink-0 py-1.5 px-3">
            I understand
          </button>
        </div>
      )}

      <div className="mt-4 sm:mt-6 card p-4 sm:p-6 max-w-full overflow-hidden">
        <ChatPanel variant="page" initialPrompt={initialPrompt} />
      </div>

      <div className="mt-3 text-center">
        <p className="text-xs text-muted">
          AI Advisor may produce inaccuracies. Verify important financial figures against official statements.
        </p>
      </div>
    </div>
  );
}
