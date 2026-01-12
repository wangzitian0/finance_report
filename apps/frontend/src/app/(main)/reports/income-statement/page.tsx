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
  filters_applied?: {
    tags: string[] | null;
    account_type: string | null;
  };
}

const toNumber = (value: number | string) => typeof value === "string" ? Number(value) : value;
const formatCurrency = (currency: string, value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
const formatMonthLabel = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short" });

const ACCOUNT_TYPE_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "INCOME", label: "Income Only" },
  { value: "EXPENSE", label: "Expenses Only" },
];

const TAG_OPTIONS = [
  { value: "", label: "All Tags" },
  { value: "business", label: "Business" },
  { value: "personal", label: "Personal" },
  { value: "investment", label: "Investment" },
  { value: "utilities", label: "Utilities" },
  { value: "transportation", label: "Transportation" },
  { value: "entertainment", label: "Entertainment" },
  { value: "food", label: "Food & Dining" },
];

export default function IncomeStatementPage() {
  const [report, setReport] = useState<IncomeStatementResponse | null>(null);
  const [startDate, setStartDate] = useState(() => { const d = new Date(); d.setMonth(d.getMonth() - 11); d.setDate(1); return formatDateInput(d); });
  const [endDate, setEndDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [accountTypeFilter, setAccountTypeFilter] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const buildQueryParams = useCallback(() => {
    const params = new URLSearchParams();
    params.set("start_date", startDate);
    params.set("end_date", endDate);
    params.set("currency", currency);
    if (accountTypeFilter) {
      params.set("account_type", accountTypeFilter);
    }
    if (selectedTags.length > 0) {
      selectedTags.forEach((tag) => params.append("tags", tag));
    }
    return params.toString();
  }, [startDate, endDate, currency, accountTypeFilter, selectedTags]);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const queryString = buildQueryParams();
      const data = await apiFetch<IncomeStatementResponse>(`/api/reports/income-statement?${queryString}`);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load income statement.");
    } finally { setLoading(false); }
  }, [buildQueryParams]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const barItems = useMemo(() => report ? report.trends.slice(-6).map((t) => ({ label: formatMonthLabel(t.period_start), income: toNumber(t.total_income), expense: toNumber(t.total_expenses) })) : [], [report]);
  const exportUrl = useMemo(() => `${API_URL}/api/reports/export?report_type=income-statement&format=csv&${buildQueryParams()}`, [buildQueryParams]);
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
        <div className="flex gap-2 flex-wrap">
          <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary text-sm">AI Interpretation</Link>
          <Link href="/dashboard" className="btn-secondary text-sm">Dashboard</Link>
          <a href={exportUrl} className="btn-secondary text-sm">Export CSV</a>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Start date</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">End date</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Currency</span><select value={currency} onChange={(e) => setCurrency(e.target.value)} className="input w-auto"><option value="SGD">SGD</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Account type</span><select value={accountTypeFilter} onChange={(e) => setAccountTypeFilter(e.target.value)} className="input w-auto">
          {ACCOUNT_TYPE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select></label>
      </div>

      <div className="flex flex-col gap-2 mb-6">
        <span className="text-xs text-muted uppercase">Tags</span>
        <div className="flex flex-wrap gap-2">
          {TAG_OPTIONS.filter((t) => t.value !== "").map((tag) => (
            <button
              key={tag.value}
              onClick={() => toggleTag(tag.value)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                selectedTags.includes(tag.value)
                  ? "bg-[var(--accent)] text-white"
                  : "bg-[var(--background-muted)] text-muted hover:bg-[var(--background-muted)]/80"
              }`}
            >
              {tag.label}
            </button>
          ))}
          {selectedTags.length > 0 && (
            <button onClick={() => setSelectedTags([])} className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--error-muted)] text-[var(--error)] hover:bg-[var(--error-muted)]/80">
              Clear all
            </button>
          )}
        </div>
      </div>

      {report?.filters_applied && (report.filters_applied.tags || report.filters_applied.account_type) && (
        <div className="mb-4 p-3 rounded-md bg-[var(--accent-muted)] text-sm">
          <span className="text-xs text-muted uppercase">Active filters: </span>
          {report.filters_applied.account_type && <span className="badge badge-primary mr-2">{report.filters_applied.account_type}</span>}
          {report.filters_applied.tags?.map((t) => <span key={t} className="badge badge-secondary mr-2">{t}</span>)}
        </div>
      )}

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
          <div className="space-y-2 max-h-64 overflow-y-auto">
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
        <div className="grid gap-2 md:grid-cols-2 max-h-96 overflow-y-auto">
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
