"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SankeyChart } from "@/components/charts/SankeyChart";
import { API_URL, apiFetch } from "@/lib/api";
import { formatDateInput } from "@/lib/date";
import { formatCurrencyLocale } from "@/lib/currency";

interface CashFlowItem {
  category: string;
  subcategory: string;
  amount: number | string;
  description: string | null;
}

interface CashFlowSummary {
  operating_activities: number | string;
  investing_activities: number | string;
  financing_activities: number | string;
  net_cash_flow: number | string;
  beginning_cash: number | string;
  ending_cash: number | string;
}

interface CashFlowResponse {
  start_date: string;
  end_date: string;
  currency: string;
  operating: CashFlowItem[];
  investing: CashFlowItem[];
  financing: CashFlowItem[];
  summary: CashFlowSummary;
}

const toNumber = (value: number | string): number => {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export default function CashFlowPage() {
  const [report, setReport] = useState<CashFlowResponse | null>(null);
  const [startDate, setStartDate] = useState(() => { const d = new Date(); d.setMonth(d.getMonth() - 1); return formatDateInput(d); });
  const [endDate, setEndDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<CashFlowResponse>(`/api/reports/cash-flow?start_date=${startDate}&end_date=${endDate}&currency=${currency}`);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load cash flow statement.");
    } finally { setLoading(false); }
  }, [currency, endDate, startDate]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const summary = useMemo(() => report?.summary, [report]);
  const exportUrl = `${API_URL}/api/reports/export?report_type=cash-flow&format=csv&start_date=${startDate}&end_date=${endDate}&currency=${currency}`;
  const aiPrompt = useMemo(() => encodeURIComponent(`Analyze my cash flow from ${startDate} to ${endDate} in ${currency}. What are the main sources and uses of cash?`), [currency, endDate, startDate]);

  const renderSection = (title: string, items: CashFlowItem[], colorClass: string) => (
    <div className="card p-5">
      <h3 className={`font-semibold mb-4 ${colorClass}`}>{title}</h3>
      {items.length > 0 ? (
        <div className="space-y-2">
          {items.map((item, idx) => (
            <div key={idx} className="flex justify-between items-center p-2 rounded-md bg-[var(--background-muted)] text-sm">
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{item.subcategory}</p>
                {item.description && <p className="text-xs text-muted truncate">{item.description}</p>}
              </div>
              <span className="font-medium ml-2">{report ? formatCurrencyLocale(toNumber(item.amount), report.currency) : "—"}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">No items in this category.</p>
      )}
    </div>
  );

  if (loading) return <div className="p-6 flex items-center justify-center min-h-[60vh]"><span className="text-muted">Loading cash flow...</span></div>;
  if (error) return <div className="p-6"><div className="card p-8 text-center max-w-md mx-auto"><p className="text-muted mb-4">{error}</p><button onClick={fetchReport} className="btn-secondary">Retry</button></div></div>;

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Cash Flow Statement</h1>
          <p className="page-description">Operating, Investing, and Financing activities</p>
        </div>
        <div className="flex gap-2">
          <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary text-sm">AI Interpretation</Link>
          <Link href="/dashboard" className="btn-secondary text-sm">Dashboard</Link>
          <a href={exportUrl} className="btn-secondary text-sm">Export CSV</a>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Start date</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">End date</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Currency</span><select value={currency} onChange={(e) => setCurrency(e.target.value)} className="input w-auto"><option value="SGD">SGD</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
      </div>

      {summary && (
        <div className="grid gap-4 md:grid-cols-3 mb-6">
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Net Cash Flow</p>
            <p className={`text-2xl font-semibold mt-1 ${toNumber(summary.net_cash_flow) >= 0 ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
              {formatCurrencyLocale(toNumber(summary.net_cash_flow), report?.currency || "SGD")}
            </p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Beginning Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(toNumber(summary.beginning_cash), report?.currency || "SGD")}</p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Ending Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(toNumber(summary.ending_cash), report?.currency || "SGD")}</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        {renderSection("Operating Activities", report?.operating || [], "text-[var(--success)]")}
        {renderSection("Investing Activities", report?.investing || [], "text-[var(--accent)]")}
        {renderSection("Financing Activities", report?.financing || [], "text-[var(--warning)]")}
      </div>

      {summary && (
        <div className="card p-5 mb-6">
          <h3 className="font-semibold mb-4">Cash Flow Visualization</h3>
          <SankeyChart
            operating={report?.operating || []}
            investing={report?.investing || []}
            financing={report?.financing || []}
            title=""
            height={350}
          />
        </div>
      )}

      {summary && (
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Summary</h3>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="p-4 rounded-md bg-[var(--success-muted)]">
              <p className="text-xs text-muted uppercase">Operating</p>
              <p className="text-xl font-semibold text-[var(--success)]">{formatCurrencyLocale(toNumber(summary.operating_activities), report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--accent-muted)]">
              <p className="text-xs text-muted uppercase">Investing</p>
              <p className="text-xl font-semibold text-[var(--accent)]">{formatCurrencyLocale(toNumber(summary.investing_activities), report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--warning-muted)]">
              <p className="text-xs text-muted uppercase">Financing</p>
              <p className="text-xl font-semibold text-[var(--warning)]">{formatCurrencyLocale(toNumber(summary.financing_activities), report?.currency || "SGD")}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
