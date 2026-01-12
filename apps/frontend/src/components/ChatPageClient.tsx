"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import ChatPanel from "@/components/ChatPanel";

const CONSENT_KEY = "ai_advisor_disclaimer_v1";

export default function ChatPageClient() {
  const searchParams = useSearchParams();
  const initialPrompt = searchParams.get("prompt");
  const [consentGiven, setConsentGiven] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = localStorage.getItem(CONSENT_KEY);
    if (stored === "accepted") setConsentGiven(true);
  }, []);

  const acceptConsent = () => {
    localStorage.setItem(CONSENT_KEY, "accepted");
    setConsentGiven(true);
  };

  return (
    <div className="p-6">
      <div className="page-header flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="page-title">AI Financial Advisor</h1>
          <p className="page-description">
            Ask about spending trends, report highlights, or reconciliation health. Read-only guidance based on posted data.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/dashboard" className="btn-secondary text-sm">Dashboard</Link>
          <Link href="/reports/balance-sheet" className="btn-secondary text-sm">Reports</Link>
        </div>
      </div>

      <div className="mt-6 card p-6">
        <ChatPanel variant="page" initialPrompt={initialPrompt} />
      </div>

      {!consentGiven && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 px-6">
          <div className="w-full max-w-lg card p-6 animate-slide-up">
            <h2 className="text-xl font-semibold">Disclaimer</h2>
            <p className="mt-3 text-sm text-muted">
              This AI financial advisor provides guidance based on your posted financial data. It
              may contain errors and does not constitute professional financial advice. Please
              consult a licensed advisor before making major decisions.
            </p>
            <div className="mt-6 flex justify-end">
              <button onClick={acceptConsent} className="btn-primary">I understand</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
