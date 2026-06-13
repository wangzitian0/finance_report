"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";

import { SankeyChart } from "@/components/charts/SankeyChart";
import { ExportCsvButton } from "@/components/reports/ExportCsvButton";
import { FxWarningBanner } from "@/components/reports/FxWarningBanner";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { formatDateInput } from "@/lib/date";
import { compareAmounts, formatCurrencyLocale, toDecimal } from "@/lib/currency";
import { useCurrencies } from "@/hooks/useCurrencies";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { CashFlowItem, CashFlowResponse } from "@/lib/types";

export default function CashFlowPage() {
  const [startDate, setStartDate] = useState(() => { const d = new Date(); d.setMonth(d.getMonth() - 1); return formatDateInput(d); });
  const [endDate, setEndDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);
  const { currencies } = useCurrencies();

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate, currency });
    return params.toString();
  }, [currency, endDate, startDate]);
  const reportQuery = useApiQuery<CashFlowResponse>(
    ["report", "cash-flow", queryString],
    `/api/reports/cash-flow?${queryString}`,
    { placeholderData: keepPreviousData },
  );
  const report = reportQuery.data ?? null;

  const summary = useMemo(() => report?.summary, [report]);
  const exportPath = `/api/reports/export?report_type=cash-flow&format=csv&${queryString}`;
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
              {item.account_id ? (
                <button
                  type="button"
                  onClick={() => setDrillTarget({
                    accountId: item.account_id!,
                    accountName: item.subcategory,
                    asOfDate: endDate,
                    startDate,
                    currency: report?.currency || currency,
                  })}
                  className="font-medium ml-2 underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                  aria-label={`View source transactions for ${item.subcategory}`}
                >
                  {report ? formatCurrencyLocale(item.amount, report.currency) : "—"}
                </button>
              ) : (
                <span className="font-medium ml-2">{report ? formatCurrencyLocale(item.amount, report.currency) : "—"}</span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">No items in this category.</p>
      )}
    </div>
  );

  if (reportQuery.isLoading) return <div className="p-6 flex items-center justify-center min-h-[60vh]"><span className="text-muted">Loading cash flow...</span></div>;
  if (reportQuery.isError) return <div className="p-6"><div className="card p-8 text-center max-w-md mx-auto"><p className="text-muted mb-4">{reportQuery.error.message}</p><button onClick={() => void reportQuery.refetch()} className="btn-secondary">Retry</button></div></div>;

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Cash Flow Statement</h1>
          <p className="page-description">Operating, Investing, and Financing activities</p>
        </div>
        <div className="flex gap-2">
          <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary text-sm">AI Interpretation</Link>
          <Link href="/" className="btn-secondary text-sm">Home</Link>
          <ExportCsvButton path={exportPath} />
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Start date</span><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">End date</span><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Currency</span><select value={currency} onChange={(e) => setCurrency(e.target.value)} className="input w-auto">{currencies.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
      </div>

      <FxWarningBanner warnings={report?.fx_warnings} />

      {summary && (
        <div className="grid gap-4 md:grid-cols-3 mb-6">
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Net Cash Flow</p>
            <p className={`text-2xl font-semibold mt-1 ${compareAmounts(summary.net_cash_flow, "0") >= 0 ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
              {formatCurrencyLocale(summary.net_cash_flow, report?.currency || "SGD")}
            </p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Beginning Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.beginning_cash, report?.currency || "SGD")}</p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Ending Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.ending_cash, report?.currency || "SGD")}</p>
          </div>
        </div>
      )}

      {summary && (() => {
        // AC22.7.3: tie beginning cash + net flow to ending cash so the user can
        // see where the period's change came from, and flag if it does not
        // reconcile.
        const cur = report?.currency || "SGD";
        const beginning = toDecimal(summary.beginning_cash);
        const net = toDecimal(summary.net_cash_flow);
        const ending = toDecimal(summary.ending_cash);
        const expectedEnding = beginning.plus(net);
        const drift = expectedEnding.minus(ending);
        const reconciles = drift.abs().lessThanOrEqualTo("0.01");
        return (
          <div className="card p-5 mb-6" aria-label="Cash reconciliation">
            <p className="text-xs text-muted uppercase mb-3">Cash reconciliation</p>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span>Beginning cash <strong>{formatCurrencyLocale(beginning, cur)}</strong></span>
              <span className="text-muted">+</span>
              <span>
                Net cash flow{" "}
                <strong className={net.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}>
                  {formatCurrencyLocale(net, cur)}
                </strong>
              </span>
              <span className="text-muted">=</span>
              <span>Ending cash <strong>{formatCurrencyLocale(ending, cur)}</strong></span>
              <span
                className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                  reconciles
                    ? "bg-[var(--success-muted)] text-[var(--success)]"
                    : "bg-[var(--warning-muted)] text-[var(--warning)]"
                }`}
              >
                {reconciles ? "✓ Reconciles" : "⚠ Does not tie"}
              </span>
            </div>
            {!reconciles && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Expected ending {formatCurrencyLocale(expectedEnding, cur)} differs from the reported ending by{" "}
                {formatCurrencyLocale(drift, cur)}.
              </p>
            )}
          </div>
        );
      })()}

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
              <p className="text-xl font-semibold text-[var(--success)]">{formatCurrencyLocale(summary.operating_activities, report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--accent-muted)]">
              <p className="text-xs text-muted uppercase">Investing</p>
              <p className="text-xl font-semibold text-[var(--accent)]">{formatCurrencyLocale(summary.investing_activities, report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--warning-muted)]">
              <p className="text-xs text-muted uppercase">Financing</p>
              <p className="text-xl font-semibold text-[var(--warning)]">{formatCurrencyLocale(summary.financing_activities, report?.currency || "SGD")}</p>
            </div>
          </div>
        </div>
      )}

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </div>
  );
}
