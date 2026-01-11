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
    if (stored === "accepted") {
      setConsentGiven(true);
    }
  }, []);

  const acceptConsent = () => {
    localStorage.setItem(CONSENT_KEY, "accepted");
    setConsentGiven(true);
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f4efe6_0%,#f7f3ea_45%,#e3ece8_100%)] text-[#13201b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-20 right-[-2rem] h-64 w-64 rounded-full bg-[#ffe0b3] blur-3xl opacity-70"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-3rem] h-72 w-72 rounded-full bg-[#bfeadf] blur-3xl opacity-60"></div>
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(15,118,110,0.08),transparent,rgba(217,119,6,0.12))] opacity-80"></div>

        <div className="relative z-10 mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-10">
          <header className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-emerald-700">Advisor Studio</p>
              <h1 className="text-4xl font-semibold text-[#0f1f17]">AI Financial Advisor</h1>
              <p className="mt-2 max-w-xl text-sm text-[#3b4b40]">
                Ask about spending trends, report highlights, or reconciliation health. This tool is
                read-only and provides guidance based on posted data.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/dashboard"
                className="rounded-full border border-emerald-200 bg-white/80 px-4 py-2 text-sm text-emerald-800"
              >
                Dashboard
              </Link>
              <Link
                href="/reports/balance-sheet"
                className="rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              >
                Reports
              </Link>
            </div>
          </header>

          <div className="mt-8 flex-1 rounded-[36px] border border-white/40 bg-white/75 p-6 shadow-xl shadow-emerald-100/40">
            <ChatPanel variant="page" initialPrompt={initialPrompt} />
          </div>
        </div>
      </div>

      {!consentGiven && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-6">
          <div className="w-full max-w-lg rounded-[32px] bg-white p-6 shadow-2xl">
            <h2 className="text-2xl font-semibold text-[#0f1f17]">Disclaimer</h2>
            <p className="mt-3 text-sm text-slate-600">
              This AI financial advisor provides guidance based on your posted financial data. It
              may contain errors or omissions and does not constitute professional financial
              advice. Please consult a licensed advisor before making major decisions.
            </p>
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                onClick={acceptConsent}
                className="rounded-full bg-emerald-600 px-5 py-2 text-sm text-white shadow-md shadow-emerald-200/60"
              >
                I understand
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
