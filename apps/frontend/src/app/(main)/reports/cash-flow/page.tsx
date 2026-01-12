import Link from "next/link";

import { SankeyChart } from "@/components/charts/SankeyChart";

export default function CashFlowPage() {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f5f0e6_0%,#f7efe1_45%,#e7eceb_100%)] text-[#13201b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-16 right-[-3rem] h-56 w-56 rounded-full bg-[#ffe1b2] blur-3xl opacity-70"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-4rem] h-72 w-72 rounded-full bg-[#baf3e6] blur-3xl opacity-60"></div>

        <div className="relative z-10 mx-auto max-w-5xl px-6 py-10">
          <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-slate-500">
                Planned for Phase 2
              </p>
              <h1 className="mt-2 text-4xl font-semibold text-[#0f1f17]">Cash Flow</h1>
              <p className="mt-2 text-sm text-[#334136]">
                Operating, investing, and financing flows will appear here once activity is tagged.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/chat?prompt=Explain%20my%20cash%20flow%20status%20and%20what%20to%20watch%20for."
                className="rounded-full border border-amber-200 bg-white/80 px-4 py-2 text-sm text-amber-700"
              >
                AI Interpretation
              </Link>
              <Link
                href="/dashboard"
                className="rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              >
                Back to Dashboard
              </Link>
            </div>
          </header>

          <div className="mt-10">
            <SankeyChart
              title="Cash flow visualization"
              description="We are preparing classification rules and FX normalization for cash flow reporting."
            />
          </div>
        </div>
      </div>
    </div>
  );
}
