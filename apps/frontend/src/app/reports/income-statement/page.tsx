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

const toNumber = (value: number | string) =>
  typeof value === "string" ? Number(value) : value;

const formatCurrency = (currency: string, value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);

const formatMonthLabel = (value: string) =>
  new Date(value).toLocaleDateString("en-US", { month: "short" });

export default function IncomeStatementPage() {
  const [report, setReport] = useState<IncomeStatementResponse | null>(null);
  const [startDate, setStartDate] = useState(() => {
    const date = new Date();
    date.setMonth(date.getMonth() - 11);
    date.setDate(1);
    return formatDateInput(date);
  });
  const [endDate, setEndDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<IncomeStatementResponse>(
        `/api/reports/income-statement?start_date=${startDate}&end_date=${endDate}&currency=${currency}`
      );
      setReport(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load income statement.");
    } finally {
      setLoading(false);
    }
  }, [currency, endDate, startDate]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const barItems = useMemo(() => {
    if (!report) return [];
    return report.trends.slice(-6).map((trend) => ({
      label: formatMonthLabel(trend.period_start),
      income: toNumber(trend.total_income),
      expense: toNumber(trend.total_expenses),
    }));
  }, [report]);

  const exportUrl = `${API_URL}/api/reports/export?report_type=income-statement&format=csv&start_date=${startDate}&end_date=${endDate}&currency=${currency}`;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f8f4ed] flex items-center justify-center text-slate-600">
        Loading income statement…
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#f8f4ed] flex flex-col items-center justify-center text-slate-600 gap-4">
        <p>{error}</p>
        <button
          onClick={fetchReport}
          className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f5f0e6_0%,#f7efe1_45%,#e7eceb_100%)] text-[#13201b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-16 right-[-3rem] h-56 w-56 rounded-full bg-[#ffe1b2] blur-3xl opacity-70"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-4rem] h-72 w-72 rounded-full bg-[#baf3e6] blur-3xl opacity-60"></div>

        <div className="relative z-10 mx-auto max-w-6xl px-6 py-10">
          <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.4em] text-amber-700">
                Performance Summary
              </p>
              <h1 className="text-4xl font-semibold text-[#0f1f17]">Income Statement</h1>
              <p className="text-sm text-[#334136]">Net Income = Income - Expenses</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/dashboard"
                className="rounded-full border border-amber-200 bg-white/80 px-4 py-2 text-sm text-amber-800"
              >
                Dashboard
              </Link>
              <a
                href={exportUrl}
                className="rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              >
                Export CSV
              </a>
            </div>
          </header>

          <section className="mt-8 flex flex-wrap items-center gap-4 text-sm">
            <label className="flex flex-col text-xs uppercase tracking-[0.2em] text-slate-500">
              Start date
              <input
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
                className="mt-2 rounded-2xl border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              />
            </label>
            <label className="flex flex-col text-xs uppercase tracking-[0.2em] text-slate-500">
              End date
              <input
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
                className="mt-2 rounded-2xl border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              />
            </label>
            <label className="flex flex-col text-xs uppercase tracking-[0.2em] text-slate-500">
              Currency
              <select
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
                className="mt-2 rounded-2xl border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-700"
              >
                <option value="SGD">SGD</option>
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
              </select>
            </label>
          </section>

          <section className="mt-8 grid gap-4 md:grid-cols-3">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Total Income</p>
              <p className="mt-3 text-2xl font-semibold text-emerald-700">
                {report ? formatCurrency(report.currency, toNumber(report.total_income)) : "—"}
              </p>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Total Expenses</p>
              <p className="mt-3 text-2xl font-semibold text-rose-500">
                {report ? formatCurrency(report.currency, toNumber(report.total_expenses)) : "—"}
              </p>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Net Income</p>
              <p className="mt-3 text-2xl font-semibold text-slate-800">
                {report ? formatCurrency(report.currency, toNumber(report.net_income)) : "—"}
              </p>
            </div>
          </section>

          <section className="mt-10 grid gap-6 lg:grid-cols-[1.2fr,1fr]">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                Monthly Comparison
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-[#101a16]">Income vs Expense</h2>
              <div className="mt-6">
                {barItems.length ? (
                  <BarChart
                    items={barItems}
                    ariaLabel="Monthly income and expense comparison"
                  />
                ) : (
                  <p className="text-sm text-slate-500">No trend data yet.</p>
                )}
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Income</p>
              <div className="mt-4 space-y-2">
                {report?.income?.length ? (
                  report.income.map((line) => (
                    <div
                      key={line.account_id}
                      className="flex items-center justify-between rounded-2xl border border-slate-100 bg-white/80 px-4 py-2 text-sm"
                    >
                      <span className="text-slate-700">{line.name}</span>
                      <span className="font-medium">
                        {formatCurrency(report.currency, toNumber(line.amount))}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">No income categories.</p>
                )}
              </div>
            </div>
          </section>

          <section className="mt-10 rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Expenses</p>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {report?.expenses?.length ? (
                report.expenses.map((line) => (
                  <div
                    key={line.account_id}
                    className="flex items-center justify-between rounded-2xl border border-slate-100 bg-white/80 px-4 py-2 text-sm"
                  >
                    <span className="text-slate-700">{line.name}</span>
                    <span className="font-medium">
                      {formatCurrency(report.currency, toNumber(line.amount))}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No expense categories.</p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
