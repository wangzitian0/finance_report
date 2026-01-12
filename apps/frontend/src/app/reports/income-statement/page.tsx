"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_URL, apiFetch } from "@/lib/api";
import { BarChart } from "@/components/charts/BarChart";
import { formatDateInput } from "@/lib/date";

interface ReportLine {
  account_id: string;
  name: string;
  type: string;
  parent_id?: string | null;
  amount: number | string;
}

interface IncomeStatementTrend {
  period_start: string;
  period_end: string;
  total_income: number | string;
  total_expenses: number | string;
  net_income: number | string;
}

interface IncomeStatementResponse {
  start_date: string;
  end_date: string;
  currency: string;
  income: ReportLine[];
  expenses: ReportLine[];
  total_income: number | string;
  total_expenses: number | string;
  net_income: number | string;
  trends: IncomeStatementTrend[];
}

const toNumber = (value: number | string) => typeof value === "string" ? Number(value) : value;
const formatCurrency = (currency: string, value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
const formatMonthLabel = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short" });

export default function IncomeStatementPage() {
  const [report, setReport] = useState<IncomeStatementResponse | null>(null);
  const [startDate, setStartDate] = useState(() => { const d = new Date(); d.setMonth(d.getMonth() - 11); d.setDate(1); return formatDateInput(d); });
  const [endDate, setEndDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<IncomeStatementResponse>(`/api/reports/income-statement?start_date=${startDate}&end_date=${endDate}&currency=${currency}`);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load income statement.");
    } finally { setLoading(false); }
  }, [currency, endDate, startDate]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const barItems = useMemo(() => report ? report.trends.slice(-6).map((t) => ({ label: formatMonthLabel(t.period_start), income: toNumber(t.total_income), expense: toNumber(t.total_expenses) })) : [], [report]);
  const exportUrl = `${API_URL}/api/reports/export?report_type=income-statement&format=csv&start_date=${startDate}&end_date=${endDate}&currency=${currency}`;
  const aiPrompt = useMemo(() => encodeURIComponent(`Summarize my income statement from ${startDate} to ${endDate} in ${currency}. Highlight key trends.`), [currency, endDate, startDate]);

  if (loading) return <div className="p-6 flex items-center justify-center min-h-[60vh]"><span className="text-muted">Loading income statement...</span></div>;
  if (error) return <div className="p-6"><div className="card p-8 text-center max-w-md mx-auto"><p className="text-muted mb-4">{error}</p><button onClick={fetchReport} className="btn-secondary">Retry</button></div></div>;

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Income Statement</h1>
          <p className="page-description">Net Income = Income - Expenses</p>
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

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <div className="card p-5"><p className="text-xs text-muted uppercase">Total Income</p><p className="text-2xl font-semibold text-[var(--success)] mt-1">{report ? formatCurrency(report.currency, toNumber(report.total_income)) : "—"}</p></div>
        <div className="card p-5"><p className="text-xs text-muted uppercase">Total Expenses</p><p className="text-2xl font-semibold text-[var(--error)] mt-1">{report ? formatCurrency(report.currency, toNumber(report.total_expenses)) : "—"}</p></div>
        <div className="card p-5"><p className="text-xs text-muted uppercase">Net Income</p><p className="text-2xl font-semibold mt-1">{report ? formatCurrency(report.currency, toNumber(report.net_income)) : "—"}</p></div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Monthly Comparison</h3>
          {barItems.length ? (
            <>
              <BarChart items={barItems} ariaLabel="Monthly income and expense comparison" />
              <div className="mt-3 flex gap-4 text-xs text-muted">
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[var(--success)]" />Income</span>
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[var(--error)]" />Expense</span>
              </div>
            </>
          ) : <p className="text-sm text-muted">No trend data yet.</p>}
        </div>
        <div className="card p-5">
          <h3 className="font-semibold mb-3">Income</h3>
          <div className="space-y-2">
            {report?.income?.length ? report.income.map((l) => (
              <div key={l.account_id} className="flex justify-between p-2 rounded-md bg-[var(--background-muted)] text-sm">
                <span>{l.name}</span><span className="font-medium">{formatCurrency(report.currency, toNumber(l.amount))}</span>
              </div>
            )) : <p className="text-sm text-muted">No income categories.</p>}
          </div>
        </div>
      </div>

      <div className="card p-5">
        <h3 className="font-semibold mb-3">Expenses</h3>
        <div className="grid gap-2 md:grid-cols-2">
          {report?.expenses?.length ? report.expenses.map((l) => (
            <div key={l.account_id} className="flex justify-between p-2 rounded-md bg-[var(--background-muted)] text-sm">
              <span>{l.name}</span><span className="font-medium">{formatCurrency(report.currency, toNumber(l.amount))}</span>
            </div>
          )) : <p className="text-sm text-muted">No expense categories.</p>}
        </div>
      </div>
    </div>
  );
}
