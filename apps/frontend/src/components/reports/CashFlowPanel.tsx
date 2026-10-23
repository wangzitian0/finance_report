"use client";

import { useState } from "react";
import { infiniteQueryOptions, keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { SankeyChart } from "@/components/charts/SankeyChart";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ExportCsvButton, FxWarningBanner, ReportPageShell, ReportToolbar } from "@/components/reports/ReportPageShell";
import { apiOperation } from "@/lib/api-client";
import { compareAmounts, formatCurrencyLocale, toDecimal } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { ReportFilters } from "@/hooks/useReportFilters";
import { cashFlowQueryKey, SHARED_STALE_MS } from "@/lib/sharedQueries";
import { countLabel } from "@/lib/statusLabels";
import { normalizeFxWarningRows, type CashFlowLine, type CashFlowLineEventsPage } from "@/lib/types";
// The cash-flow statement carries an event count for each line (#2583 S10). The events of a
// line load page by page when the user opens the line. This component mounts only for an open
// line, so a closed line never issues a request. Each page request runs the cash-flow builder
// again, so a page holds 200 events and the open and reopened line share one cache entry.

/** Page size of the line events. The backend maximum is 500. */
const CASH_FLOW_LINE_EVENTS_PAGE_SIZE = 200;

interface CashFlowPeriod {
  start_date: string;
  end_date: string;
  currency: string;
}

/** The accessible name of a line: its description holds the direction and the counterparts. */
function cashFlowLineLabel(line: CashFlowLine): string {
  return line.description || line.subcategory;
}

function nextOffset(page: CashFlowLineEventsPage): number | undefined {
  const next = page.offset + page.limit;
  return next < page.total ? next : undefined;
}

/** The one cache entry of the events of a line. The "report" key prefix is ledger-derived. */
function cashFlowLineEventsQueryOptions(period: CashFlowPeriod, lineId: string) {
  return infiniteQueryOptions({
    queryKey: ["report", "cash-flow", "line-events", period.start_date, period.end_date, period.currency, lineId] as const,
    queryFn: ({ pageParam, signal }) =>
      apiOperation("list_cash_flow_line_events_reports_cash_flow_line_events_get", {
        query: { ...period, line_id: lineId, limit: CASH_FLOW_LINE_EVENTS_PAGE_SIZE, offset: pageParam },
        signal,
      }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    staleTime: SHARED_STALE_MS,
  });
}

/** The events of one open cash-flow line, with the amounts in the report currency. */
function CashFlowLineEvents({ period, line }: { period: CashFlowPeriod; line: CashFlowLine }) {
  const query = useInfiniteQuery(cashFlowLineEventsQueryOptions(period, line.line_id));
  const events = query.data?.pages.flatMap((page) => page.events ?? []) ?? [];
  const total = query.data?.pages[0]?.total ?? line.event_count;

  return (
    <section
      id={`cash-flow-events-${line.line_id}`}
      aria-label={`Events for ${cashFlowLineLabel(line)}`}
      className="mt-2 rounded-md border border-[var(--border)] p-2"
    >
      <p className="text-xs font-medium">{`${events.length} of ${countLabel(total, "event")}`}</p>
      {query.isLoading ? (
        <p role="status" className="mt-1 text-xs text-muted">
          Loading events...
        </p>
      ) : null}
      {events.length > 0 ? (
        <ul className="mt-1 max-h-64 space-y-1 overflow-y-auto pr-1">
          {events.map((event) => (
            <li key={`${event.journal_entry_id}-${event.reason_code ?? ""}`} className="flex justify-between gap-2 text-xs">
              <span className="min-w-0">
                <span className="text-muted">{formatDateDisplay(event.entry_date)}</span>{" "}
                <span className="break-words">{event.memo}</span>
              </span>
              <span className="shrink-0 font-medium">{formatCurrencyLocale(event.amount, period.currency)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {query.error ? (
        <p className="mt-1 text-xs text-[var(--error)]">
          {query.error instanceof Error ? query.error.message : "Failed to load the events."}
        </p>
      ) : null}
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary mt-2 text-xs"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : "Load more events"}
        </button>
      ) : null}
    </section>
  );
}

/** The Cash flow tab of `/reports`: cash movements of the dimension-bar period. */
export function CashFlowPanel({ filters }: { filters: ReportFilters }) {
  const { startDate, endDate, currency } = filters;
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);
  // Open lines, keyed by the report period and the line id: a new period starts with every line closed.
  const [openLines, setOpenLines] = useState<ReadonlySet<string>>(new Set());

  const reportQuery = useApiQuery(
    cashFlowQueryKey({ startDate, endDate, currency }),
    "cash_flow_reports_cash_flow_get",
    { query: { start_date: startDate, end_date: endDate, currency } },
    {
      // The period waits for the first statement (#2646).
      enabled: filters.ready,
      placeholderData: keepPreviousData,
      select: (data) => ({ ...data, fx_warnings: normalizeFxWarningRows(data.fx_warnings) }),
    },
  );
  const report = reportQuery.data ?? null;
  const period: CashFlowPeriod | null = report
    ? { start_date: report.start_date, end_date: report.end_date, currency: report.currency }
    : null;
  const openKey = (line: CashFlowLine) => (period ? `${period.start_date}|${period.end_date}|${period.currency}|${line.line_id}` : "");
  const toggleLine = (key: string) =>
    setOpenLines((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const incompleteOpeningCoverage = report?.proof_reasons?.includes("opening_coverage_starts_after_period") ?? false;
  const unverified = report?.proof_state === "unproven";
  const summary = report?.summary;
  const aiPrompt = `Analyze my cash flow from ${startDate} to ${endDate} in ${report?.currency ?? currency ?? "my base currency"}. What are the main sources and uses of cash?`;

  const renderSection = (title: string, lines: CashFlowLine[], colorClass: string) => (
    <div className="card p-5">
      <h3 className={`font-semibold mb-4 ${colorClass}`}>{title}</h3>
      {lines.length > 0 ? (
        <div className="space-y-2">
          {lines.map((line, idx) => {
            const key = openKey(line);
            const open = period !== null && openLines.has(key);
            const label = cashFlowLineLabel(line);
            return (
              <div key={line.line_id ?? `${line.subcategory}-${idx}`} className="p-2 rounded-md bg-[var(--background-muted)] text-sm">
                <div className="flex justify-between items-center">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{line.subcategory}</p>
                    {line.description && <p className="text-xs text-muted truncate">{line.description}</p>}
                  </div>
                  {line.account_id ? (
                    <button
                      type="button"
                      onClick={() =>
                        setDrillTarget({
                          accountId: line.account_id!,
                          accountName: line.subcategory,
                          asOfDate: endDate,
                          startDate,
                          currency: report!.currency,
                        })
                      }
                      className="font-medium ml-2 underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                      aria-label={`View source transactions for ${line.subcategory}`}
                    >
                      {report ? formatCurrencyLocale(line.amount, report.currency) : "—"}
                    </button>
                  ) : (
                    <span className="font-medium ml-2">{report ? formatCurrencyLocale(line.amount, report.currency) : "—"}</span>
                  )}
                </div>
                {period && line.event_count > 0 ? (
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`cash-flow-events-${line.line_id}`}
                    aria-label={`${countLabel(line.event_count, "event")} for ${label}`}
                    onClick={() => toggleLine(key)}
                    className="mt-1 text-xs text-muted underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                  >
                    {countLabel(line.event_count, "event")}
                  </button>
                ) : null}
                {open && period ? <CashFlowLineEvents period={period} line={line} /> : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted">No items in this category.</p>
      )}
    </div>
  );

  return (
    <ReportPageShell
      title="Cash Flow Statement"
      description="Operating, Investing, and Financing activities"
      loadingLabel="Loading cash flow"
      isLoading={!filters.ready || reportQuery.isLoading}
      isError={reportQuery.isError}
      errorMessage={reportQuery.error?.message}
      onRetry={() => void reportQuery.refetch()}
      toolbar={
        <ReportToolbar
          aiPrompt={aiPrompt}
          exportControl={<ExportCsvButton request={{ query: { report_type: "cash-flow", format: "csv", start_date: startDate, end_date: endDate, currency } }} />}
        />
      }
    >
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
            <p className="text-xs text-muted uppercase">{incompleteOpeningCoverage ? "Known Beginning Cash" : "Beginning Cash"}</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.beginning_cash, report?.currency || "SGD")}</p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Ending Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.ending_cash, report?.currency || "SGD")}</p>
          </div>
        </div>
      )}

      {summary && (() => {
        const cur = report?.currency || "SGD";
        const beginning = toDecimal(summary.beginning_cash);
        const net = toDecimal(summary.net_cash_flow);
        const ending = toDecimal(summary.ending_cash);
        const openingStock = toDecimal(report?.cash_bridge?.opening_stock_adjustment ?? "0");
        const expectedEnding = beginning.plus(net).plus(openingStock);
        const drift = expectedEnding.minus(ending);
        const reconciles = drift.abs().lessThanOrEqualTo("0.01");
        return (
          <div className="card p-5 mb-6" aria-label="Cash reconciliation">
            <p className="text-xs text-muted uppercase mb-3">Cash reconciliation</p>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span>{incompleteOpeningCoverage ? "Known beginning cash" : "Beginning cash"} <strong>{formatCurrencyLocale(beginning, cur)}</strong></span>
              <span className="text-muted">+</span>
              <span>Net cash flow <strong className={net.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}>{formatCurrencyLocale(net, cur)}</strong></span>
              {!openingStock.isZero() && (
                <>
                  <span className="text-muted">+</span>
                  <span>Opening balance adjustment <strong>{formatCurrencyLocale(openingStock, cur)}</strong></span>
                </>
              )}
              <span className="text-muted">=</span>
              <span>Ending cash <strong>{formatCurrencyLocale(ending, cur)}</strong></span>
              <span className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${reconciles && !unverified ? "bg-[var(--success-muted)] text-[var(--success)]" : "bg-[var(--warning-muted)] text-[var(--warning)]"}`}>
                {!reconciles ? "⚠ Does not tie" : incompleteOpeningCoverage ? "⚠ Coverage incomplete" : unverified ? "⚠ Not yet verified" : "✓ Reconciles"}
              </span>
            </div>
            {incompleteOpeningCoverage && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Records start after the selected period begins. Beginning cash is only the known amount; full-period cash flow is not yet verified.
              </p>
            )}
            {unverified && !incompleteOpeningCoverage && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                {report?.proof_reasons?.includes("opening_position_unproven")
                  ? "Opening balance evidence needs review before cash flow can be verified."
                  : "Cash flow evidence needs review before this report can be verified."}
              </p>
            )}
            {!reconciles && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Expected ending {formatCurrencyLocale(expectedEnding, cur)} differs from the reported ending by {formatCurrencyLocale(drift.abs(), cur)} — the reported ending is {drift.isPositive() ? "lower" : "higher"} than expected.
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
          <SankeyChart operating={report?.operating || []} investing={report?.investing || []} financing={report?.financing || []} title="" height={350} />
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
    </ReportPageShell>
  );
}
