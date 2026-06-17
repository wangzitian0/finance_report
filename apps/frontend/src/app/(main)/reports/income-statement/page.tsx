"use client";

import { useMemo, useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";

import { BarChart } from "@/components/charts/BarChart";
import { FxWarningBanner } from "@/components/reports/FxWarningBanner";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ReportPageShell } from "@/components/reports/ReportPageShell";
import { ReportToolbar } from "@/components/reports/ReportToolbar";
import { ExportCsvButton } from "@/components/reports/ExportCsvButton";
import { CurrencyFilterControl, DateFilterControl } from "@/components/reports/ReportFilters";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { formatDateInput, formatMonthLabel } from "@/lib/date";
import { amountToChartNumber, formatCurrencyLocale } from "@/lib/money";
import { useCurrencies } from "@/hooks/useCurrencies";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useReportFilters } from "@/hooks/useReportFilters";
import type { IncomeStatementResponse } from "@/lib/types";

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

const defaultStartDate = () => {
  const d = new Date();
  d.setMonth(d.getMonth() - 11);
  d.setDate(1);
  return formatDateInput(d);
};

export default function IncomeStatementPage() {
  const { startDate, setStartDate, endDate, setEndDate, currency, setCurrency } = useReportFilters({
    reportType: "income-statement",
    initialStartDate: defaultStartDate(),
  });
  const [accountTypeFilter, setAccountTypeFilter] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);
  const { currencies } = useCurrencies();

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const queryString = useMemo(() => {
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
  const reportQuery = useApiQuery<IncomeStatementResponse>(
    ["report", "income-statement", queryString],
    `/api/reports/income-statement?${queryString}`,
    { placeholderData: keepPreviousData },
  );
  const report = reportQuery.data ?? null;

  const barItems = useMemo(() => report ? report.trends.slice(-6).map((t) => ({ label: formatMonthLabel(t.period_start), income: amountToChartNumber(t.total_income), expense: amountToChartNumber(t.total_expenses) })) : [], [report]);
  const exportPath = useMemo(() => `/api/reports/export?report_type=income-statement&format=csv&${queryString}`, [queryString]);
  const aiPrompt = useMemo(() => `Summarize my income statement from ${startDate} to ${endDate} in ${currency}. Highlight key trends.`, [currency, endDate, startDate]);

  return (
    <ReportPageShell
      title="Income Statement"
      description="Net Income = Income - Expenses"
      loadingLabel="Loading income statement"
      loadingSections={2}
      isLoading={reportQuery.isLoading}
      isError={reportQuery.isError}
      errorMessage={reportQuery.error?.message}
      onRetry={() => void reportQuery.refetch()}
      toolbar={
        <ReportToolbar
          aiPrompt={aiPrompt}
          exportControl={<ExportCsvButton path={exportPath} />}
        />
      }
    >
      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <DateFilterControl label="Start date" value={startDate} onChange={setStartDate} />
        <DateFilterControl label="End date" value={endDate} onChange={setEndDate} />
        <CurrencyFilterControl value={currency} currencies={currencies} onChange={setCurrency} />
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
          {report.filters_applied.tags?.map((t) => <span key={t} className="badge badge-muted mr-2">{t}</span>)}
        </div>
      )}

      <FxWarningBanner warnings={report?.fx_warnings} />

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <div className="card p-5"><p className="text-xs text-muted uppercase">Total Income</p><p className="text-2xl font-semibold text-[var(--success)] mt-1">{report ? formatCurrencyLocale(report.total_income, report.currency) : "—"}</p></div>
        <div className="card p-5"><p className="text-xs text-muted uppercase">Total Expenses</p><p className="text-2xl font-semibold text-[var(--error)] mt-1">{report ? formatCurrencyLocale(report.total_expenses, report.currency) : "—"}</p></div>
        <div className="card p-5"><p className="text-xs text-muted uppercase">Net Income</p><p className="text-2xl font-semibold mt-1">{report ? formatCurrencyLocale(report.net_income, report.currency) : "—"}</p></div>
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
                <span className="flex min-w-0 items-center gap-2">
                  <span>{l.name}</span>
                  <ProvenanceBadge provenance={l.provenance} />
                </span>
                <button
                  type="button"
                  className="font-medium tabular-nums hover:text-[var(--accent)] hover:underline"
                  onClick={() =>
                    setDrillTarget({
                      accountId: l.account_id,
                      accountName: l.name,
                      asOfDate: endDate,
                      startDate,
                      currency: report.currency,
                    })
                  }
                  aria-label={`View source transactions for ${l.name}`}
                >
                  {formatCurrencyLocale(l.amount, report.currency)}
                </button>
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
              <span className="flex min-w-0 items-center gap-2">
                <span>{l.name}</span>
                <ProvenanceBadge provenance={l.provenance} />
              </span>
              <button
                type="button"
                className="font-medium tabular-nums hover:text-[var(--accent)] hover:underline"
                onClick={() =>
                  setDrillTarget({
                    accountId: l.account_id,
                    accountName: l.name,
                    asOfDate: endDate,
                    startDate,
                    currency: report.currency,
                  })
                }
                aria-label={`View source transactions for ${l.name}`}
              >
                {formatCurrencyLocale(l.amount, report.currency)}
              </button>
            </div>
          )) : <p className="text-sm text-muted">No expense categories.</p>}
        </div>
      </div>

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}
