"use client";

import { keepPreviousData } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { BarChart } from "@/components/charts/BarChart";
import { AccountLineageDrawer, ExcludedHoldingsNote, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import {
  ExportCsvButton,
  FxWarningBanner,
  OpeningBalanceWarningBanner,
  ReportPageShell,
  ReportToolbar,
} from "@/components/reports/ReportShell";
import { InfoHint } from "@/components/ui/InfoHint";
import { ProvenanceBadge } from "@/components/ui";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { ReportFilters } from "@/hooks/useReportFilters";
import { amountToChartNumber, formatCurrencyLocale, sumAmounts, toDecimal } from "@/lib/audit/money";
import { formatMonthLabel } from "@/lib/date";
import { balanceSheetQueryKey, incomeStatementQueryKey } from "@/lib/sharedQueries";
import { liabilityToneClass, reportAccountDisplayName } from "@/lib/statusLabels";
import { normalizeFxWarningRows, type NetWorthTimeSeriesResponse, type ReportLine } from "@/lib/types";

// ECharts loads only when a chart renders, so a page without this chart does not carry it.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

/** A period up to this many days draws one point per day. A longer period draws one point per month. */
const DAILY_GRANULARITY_MAX_DAYS = 92;
const DAY_MS = 24 * 60 * 60 * 1000;

function granularityFor(from: string, to: string): "daily" | "monthly" {
  const days = (Date.parse(to) - Date.parse(from)) / DAY_MS;
  return days <= DAILY_GRANULARITY_MAX_DAYS ? "daily" : "monthly";
}

// A revisit of the tab or of a period within this time reuses the cached series (#2583).
const NET_WORTH_SERIES_STALE_TIME_MS = 60_000;

/**
 * The net worth history of the dimension-bar period (#2621 LC). The bar is the only period control.
 * The series uses the restricted-holdings scope of the bar, so its last point equals the net worth
 * of the balance sheet on the same date (#2645).
 */
export function NetWorthTimeSeriesChart({
  from,
  to,
  currency,
  includeRestricted,
  enabled = true,
}: {
  from: string;
  to: string;
  currency?: string;
  includeRestricted: boolean;
  /** False while `from` can still move: the chart shows its loading state and does not fetch. */
  enabled?: boolean;
}) {
  const granularity = granularityFor(from, to);
  const seriesQuery = useApiQuery(
    ["report", "net-worth-timeseries", from, to, granularity, currency ?? "", includeRestricted],
    "net_worth_timeseries_reports_net_worth_timeseries_get",
    { query: { from, to, granularity, currency, include_restricted: includeRestricted } },
    { staleTime: NET_WORTH_SERIES_STALE_TIME_MS, enabled },
  );
  const data: NetWorthTimeSeriesResponse | undefined = seriesQuery.data;
  const loading = seriesQuery.isPending;
  const error = seriesQuery.error
    ? seriesQuery.error.message || "Failed to load net worth history."
    : null;

  const points = useMemo(() => data?.points ?? [], [data?.points]);
  const option = useMemo(() => {
    const labels = points.map((point) =>
      data?.granularity === "monthly"
        ? formatMonthLabel(point.date)
        : point.date.slice(5),
    );
    const values = points.map((point) => amountToChartNumber(point.net_worth));
    return {
      grid: { left: 48, right: 18, top: 24, bottom: 32 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number) =>
          formatCurrencyLocale(value, data?.currency ?? "SGD"),
      },
      xAxis: { type: "category", data: labels, boundaryGap: false },
      yAxis: { type: "value" },
      series: [
        {
          name: "Net Worth",
          type: "line",
          smooth: true,
          showSymbol: false,
          data: values,
          lineStyle: { color: "#2563eb", width: 2 },
          areaStyle: { color: "rgba(37, 99, 235, 0.10)" },
        },
      ],
    };
  }, [data?.currency, data?.granularity, points]);

  return (
    <section className="card p-5 min-w-0 overflow-hidden" aria-label="Net worth time-series">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-muted uppercase tracking-wide">
            Net Worth History
          </p>
          <h3 className="font-semibold mt-1">{granularity === "daily" ? "Daily net worth" : "Monthly net worth"}</h3>
        </div>
      </div>
      {loading ? (
        <p className="text-sm text-muted">Loading net worth history...</p>
      ) : error ? (
        <p className="text-sm text-[var(--error)]">{error}</p>
      ) : points.length < 2 ? (
        <p className="text-sm text-muted">
          At least two net worth points are needed to draw a line.
        </p>
      ) : (
        <div data-testid="net-worth-echarts">
          <ReactECharts
            option={option}
            style={{ height: 260, width: "100%" }}
            notMerge
            lazyUpdate
          />
        </div>
      )}
    </section>
  );
}

interface AccountNode extends ReportLine {
  children: AccountNode[];
}

const buildTree = (lines: ReportLine[]): AccountNode[] => {
  const nodes = new Map<string, AccountNode>();
  lines.forEach((line) => nodes.set(line.account_id, { ...line, children: [] }));
  const roots: AccountNode[] = [];
  nodes.forEach((node) => {
    if (node.parent_id && nodes.has(node.parent_id)) nodes.get(node.parent_id)?.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (items: AccountNode[]) => {
    items.sort((a, b) => a.name.localeCompare(b.name));
    items.forEach((item) => sortNodes(item.children));
  };
  sortNodes(roots);
  return roots;
};

/** The Balance sheet tab of `/reports`: the position at the end of the dimension-bar period. */
export function BalanceSheetPanel({ filters }: { filters: ReportFilters }) {
  const { startDate, endDate: asOfDate, currency, includeRestricted } = filters;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);

  const reportQuery = useApiQuery(
    balanceSheetQueryKey({ asOfDate, currency, includeRestricted }),
    "balance_sheet_reports_balance_sheet_get",
    { query: { as_of_date: asOfDate, currency, include_restricted: includeRestricted } },
    {
      placeholderData: keepPreviousData,
      select: (data) => ({
        ...data,
        fx_warnings: normalizeFxWarningRows(data.fx_warnings),
        opening_balance_warnings: normalizeFxWarningRows(data.opening_balance_warnings),
      }),
    },
  );
  const report = reportQuery.data ?? null;

  useEffect(() => {
    if (!report) return;
    const rootIds = new Set<string>();
    [...report.assets, ...report.liabilities, ...report.equity].forEach((line) => {
      if (!line.parent_id) rootIds.add(line.account_id);
    });
    setExpanded(rootIds);
  }, [report]);

  const assetsTree = useMemo(() => (report ? buildTree(report.assets) : []), [report]);
  const liabilitiesTree = useMemo(() => (report ? buildTree(report.liabilities) : []), [report]);
  const equityTree = useMemo(() => (report ? buildTree(report.equity) : []), [report]);
  // Two equity lines (#2645): FX and CTA come from currency translation. The valuation line is
  // the net of the manual valuations and the portfolio market adjustments. A manual liability
  // valuation, for example a mortgage, is never an FX or CTA amount.
  const fxAndCta = report ? sumAmounts([report.unrealized_fx_gain_loss ?? 0, report.cta_adjustment ?? 0]) : null;
  const valuationAdjustment = report ? toDecimal(report.net_worth_adjustment_gain_loss ?? 0) : null;
  const aiPrompt = `Explain my balance sheet as of ${asOfDate} in ${report?.currency ?? currency ?? "my base currency"}. Highlight any risks.`;

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const renderNode = (node: AccountNode, depth = 0) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expanded.has(node.account_id);
    const displayName = reportAccountDisplayName(node.name);
    const isManualValuation =
      node.allocation_source_type === "manual_valuation" ||
      (!node.allocation_source_type && node.provenance === "manual");
    const openDrill = () =>
      report &&
      !isManualValuation &&
      setDrillTarget({ accountId: node.account_id, accountName: displayName, asOfDate, currency: report.currency });
    const isForeign = Boolean(report && node.source_currency && node.source_currency !== report.currency);
    const hasNativeAmount = node.native_amount !== undefined && node.native_amount !== null;
    const missingFxConversion =
      isForeign && hasNativeAmount && !toDecimal(node.native_amount!).isZero() && toDecimal(node.amount).isZero();
    return (
      <div
        key={node.account_id}
        role="treeitem"
        aria-level={depth + 1}
        aria-selected={false}
        aria-expanded={hasChildren ? isExpanded : undefined}
      >
        <div
          className="flex items-center justify-between gap-2 px-3 py-2 text-sm rounded-md hover:bg-[var(--background-muted)]/50 min-w-0"
          style={{ paddingLeft: depth * 16 + 12 }}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            {hasChildren && (
              <button
                onClick={() => toggle(node.account_id)}
                aria-label={isExpanded ? `Collapse ${displayName}` : `Expand ${displayName}`}
                className="-my-2 flex h-11 w-11 shrink-0 items-center justify-center text-base leading-none text-[var(--foreground-muted)] hover:text-[var(--foreground)]"
              >
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[var(--background-muted)] text-xs" aria-hidden="true">
                  {isExpanded ? "–" : "+"}
                </span>
              </button>
            )}
            {isManualValuation ? (
              <Link href="/portfolio?panel=evidence" className="truncate text-left hover:text-[var(--accent)] hover:underline">
                {displayName}
              </Link>
            ) : (
              <button type="button" onClick={openDrill} className="truncate text-left hover:text-[var(--accent)] hover:underline">
                {displayName}
              </button>
            )}
            {node.name === "Processing" && <InfoHint term="transfers_in_transit" label="Transfers in transit" />}
            {isForeign && node.source_currency && (
              <span className="badge badge-muted text-[11px] shrink-0">{node.source_currency}</span>
            )}
            <ProvenanceBadge provenance={node.provenance} />
          </div>
          {report ? (
            <div className="flex flex-col items-end shrink-0">
              {isManualValuation ? (
                <Link
                  href="/portfolio?panel=evidence"
                  className="font-medium tabular-nums whitespace-nowrap underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                  aria-label={`View valuation evidence for ${displayName}`}
                >
                  {formatCurrencyLocale(node.amount, report.currency)}
                </Link>
              ) : (
                <button
                  type="button"
                  className="font-medium tabular-nums whitespace-nowrap underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                  onClick={openDrill}
                  aria-label={`View source transactions for ${displayName}`}
                >
                  {formatCurrencyLocale(node.amount, report.currency)}
                </button>
              )}
              {isForeign && hasNativeAmount && (
                <span className={`text-xs tabular-nums whitespace-nowrap ${missingFxConversion ? "text-[var(--warning)]" : "text-muted"}`}>
                  {formatCurrencyLocale(node.native_amount!, node.source_currency!)}
                  {missingFxConversion ? " · No FX rate" : ""}
                </span>
              )}
            </div>
          ) : (
            <span className="font-medium shrink-0">—</span>
          )}
        </div>
        {hasChildren && isExpanded && (
          <div role="group" className="ml-2 border-l border-[var(--border)] pl-2">
            {node.children.map((c) => renderNode(c, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <ReportPageShell
      title="Balance Sheet"
      description="Assets = Liabilities + Equity"
      loadingLabel="Loading balance sheet"
      isLoading={reportQuery.isLoading}
      isError={reportQuery.isError}
      errorMessage={reportQuery.error?.message}
      onRetry={() => void reportQuery.refetch()}
      toolbar={
        <ReportToolbar
          aiPrompt={aiPrompt}
          exportControl={
            <ExportCsvButton
              request={{ query: { report_type: "balance-sheet", format: "csv", as_of_date: asOfDate, currency, include_restricted: includeRestricted } }}
            />
          }
        >
          <span className="inline-flex items-center">
            <span className={`badge ${report?.is_balanced ? "badge-success" : "badge-warning"}`}>
              {report?.is_balanced ? "✓ Balanced" : "⚠ Drift"}
            </span>
            <InfoHint term={report?.is_balanced ? "balanced" : "drift"} label={report?.is_balanced ? "Balanced" : "Drift"} />
          </span>
        </ReportToolbar>
      }
    >
      <FxWarningBanner warnings={report?.fx_warnings} />
      <OpeningBalanceWarningBanner warnings={report?.opening_balance_warnings} />

      {report && report.is_balanced === false && (
        <div role="alert" className="p-4 mb-6 bg-[var(--error)]/10 border border-[var(--error)] rounded-lg flex items-center justify-between text-[var(--error)]">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm">Accounting Equation Imbalance Detected</span>
            <span className="text-xs">
              Assets do not match Liabilities + Equity (Delta: {formatCurrencyLocale(report.equation_delta, report.currency)}).
            </span>
          </div>
        </div>
      )}

      <details className="card mb-6 group min-w-0 overflow-hidden" data-testid="balance-equation-detail">
        <summary className="p-4 font-semibold cursor-pointer list-none flex items-center justify-between gap-2 hover:bg-[var(--background-muted)] rounded-lg transition-colors select-none min-w-0">
          <span className="flex flex-wrap items-center gap-2 min-w-0">
            <span>Balance Equation Detail</span>
            <span className="text-xs font-normal text-muted whitespace-nowrap">
              {report?.is_balanced ? "Books in balance" : report ? `Delta: ${formatCurrencyLocale(report.equation_delta, report.currency)}` : "—"}
            </span>
          </span>
          <span className="text-xs text-muted group-open:rotate-180 transition-transform shrink-0">▼</span>
        </summary>
        <div className="p-5 pt-1 border-t border-[var(--border)] min-w-0">
          <dl className="grid gap-3 text-sm grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            <div className="min-w-0">
              <dt className="text-xs text-muted uppercase truncate">Net Income</dt>
              <dd className="mt-1 font-medium tabular-nums whitespace-nowrap">{report ? formatCurrencyLocale(report.net_income ?? 0, report.currency) : "—"}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted uppercase truncate">Unrealized FX</dt>
              <dd className="mt-1 font-medium tabular-nums whitespace-nowrap">{report ? formatCurrencyLocale(report.unrealized_fx_gain_loss ?? 0, report.currency) : "—"}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted uppercase truncate">Net Worth Adjustment</dt>
              <dd className="mt-1 font-medium tabular-nums whitespace-nowrap">{report ? formatCurrencyLocale(report.net_worth_adjustment_gain_loss ?? 0, report.currency) : "—"}</dd>
            </div>
            <div className="min-w-0" data-testid="equation-detail-cta">
              <dt className="text-xs text-muted uppercase truncate">CTA Adjustment</dt>
              <dd className="mt-1 font-medium tabular-nums whitespace-nowrap" aria-label="Currency translation adjustment">
                {report ? formatCurrencyLocale(report.cta_adjustment ?? "0.00", report.currency) : "—"}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted uppercase truncate">Equation Delta</dt>
              <dd className="mt-1 font-medium tabular-nums whitespace-nowrap">{report ? formatCurrencyLocale(report.equation_delta, report.currency) : "—"}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-muted uppercase truncate">Restricted Treatment</dt>
              <dd className="mt-1 font-medium">{includeRestricted ? "Included" : "Excluded"}</dd>
            </div>
          </dl>
        </div>
      </details>

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <div className="card p-5 min-w-0 overflow-hidden" id="assets">
          <h2 className="font-semibold mb-3">Assets</h2>
          <div role="tree" aria-label="Balance Sheet - Assets" className="space-y-1 min-w-0">
            {assetsTree.length ? assetsTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--success)] whitespace-nowrap">
            Total: {report ? formatCurrencyLocale(report.total_assets, report.currency) : "—"}
          </div>
        </div>
        <div className="card p-5 min-w-0 overflow-hidden" id="liabilities">
          <h2 className="font-semibold mb-3">Liabilities</h2>
          <div role="tree" aria-label="Balance Sheet - Liabilities" className="space-y-1 min-w-0">
            {liabilitiesTree.length ? liabilitiesTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className={`mt-4 pt-3 border-t border-[var(--border)] font-semibold whitespace-nowrap ${report ? liabilityToneClass(report.total_liabilities) : "text-muted"}`}>
            Total: {report ? formatCurrencyLocale(report.total_liabilities, report.currency) : "—"}
          </div>
        </div>
        <div className="card p-5 min-w-0 overflow-hidden" id="equity">
          <h2 className="font-semibold mb-3">Equity</h2>
          <div role="tree" aria-label="Balance Sheet - Equity" className="space-y-1 min-w-0">
            {equityTree.length ? equityTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] space-y-1 text-sm min-w-0">
            <div className="flex justify-between gap-2 text-muted min-w-0">
              <span className="min-w-0 truncate">Opening Equity:</span>
              <span className="whitespace-nowrap shrink-0 tabular-nums">{report ? formatCurrencyLocale(report.total_equity, report.currency) : "—"}</span>
            </div>
            <div className="flex justify-between gap-2 text-muted min-w-0">
              <span className="min-w-0 truncate">Net Income (P&L):</span>
              <span className={`whitespace-nowrap shrink-0 tabular-nums ${report && toDecimal(report.net_income ?? 0).isNegative() ? "text-[var(--error)] font-medium" : "text-[var(--success)] font-medium"}`}>
                {report ? formatCurrencyLocale(report.net_income ?? 0, report.currency) : "—"}
              </span>
            </div>
            {report && fxAndCta && !fxAndCta.isZero() && (
              <div className="flex justify-between gap-2 text-muted min-w-0" data-testid="equity-fx-cta">
                <span className="min-w-0 truncate">FX and translation (CTA):</span>
                <span className="whitespace-nowrap shrink-0 tabular-nums">{formatCurrencyLocale(fxAndCta, report.currency)}</span>
              </div>
            )}
            {report && valuationAdjustment && !valuationAdjustment.isZero() && (
              <div className="flex justify-between gap-2 text-muted min-w-0" data-testid="equity-valuations">
                <span className="min-w-0 truncate">Manual and market valuations:</span>
                <span className="whitespace-nowrap shrink-0 tabular-nums">{formatCurrencyLocale(valuationAdjustment, report.currency)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-[var(--border)] font-semibold flex justify-between gap-2 min-w-0">
              <span className="min-w-0 truncate">Total:</span>
              <span className="whitespace-nowrap shrink-0 tabular-nums">
                {report && fxAndCta && valuationAdjustment
                  ? formatCurrencyLocale(
                      sumAmounts([report.total_equity, report.net_income ?? 0, fxAndCta, valuationAdjustment]),
                      report.currency,
                    )
                  : "—"}
              </span>
            </div>
            {report && (
              <ExcludedHoldingsNote rows={report.excluded_holdings} currency={report.currency} formatMoney={formatCurrencyLocale} />
            )}
          </div>
        </div>
      </div>

      {/* The coverage start can move `startDate`: the series waits for it (#2646). */}
      <NetWorthTimeSeriesChart
        from={startDate}
        to={asOfDate}
        currency={currency}
        includeRestricted={includeRestricted}
        enabled={filters.ready}
      />

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}

const ACCOUNT_TYPE_OPTIONS = [
  { value: "", label: "All Types" },
  { value: "INCOME", label: "Income Only" },
  { value: "EXPENSE", label: "Expenses Only" },
] as const;

const TAG_OPTIONS = [
  { value: "business", label: "Business" },
  { value: "personal", label: "Personal" },
  { value: "investment", label: "Investment" },
  { value: "utilities", label: "Utilities" },
  { value: "transportation", label: "Transportation" },
  { value: "entertainment", label: "Entertainment" },
  { value: "food", label: "Food & Dining" },
];

/** The Income statement tab of `/reports`: income and expenses of the dimension-bar period. */
export function IncomeStatementPanel({ filters }: { filters: ReportFilters }) {
  const { startDate, endDate, currency } = filters;
  const [accountTypeFilter, setAccountTypeFilter] = useState<(typeof ACCOUNT_TYPE_OPTIONS)[number]["value"]>("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const reportKey = incomeStatementQueryKey({
    startDate,
    endDate,
    currency,
    accountType: accountTypeFilter || undefined,
    tags: selectedTags,
  });
  const reportQuery = useApiQuery(
    reportKey,
    "income_statement_reports_income_statement_get",
    {
      query: {
        start_date: startDate,
        end_date: endDate,
        currency,
        account_type: accountTypeFilter || undefined,
        tags: selectedTags.length ? selectedTags : undefined,
      },
    },
    {
      // The period waits for the coverage start (#2646).
      enabled: filters.ready,
      placeholderData: keepPreviousData,
      select: (data) => ({ ...data, fx_warnings: normalizeFxWarningRows(data.fx_warnings) }),
    },
  );
  const report = reportQuery.data ?? null;

  const barItems = useMemo(
    () =>
      report
        ? report.trends.slice(-12).map((t) => ({
            label: formatMonthLabel(t.period_start),
            income: amountToChartNumber(t.total_income),
            expense: amountToChartNumber(t.total_expenses),
          }))
        : [],
    [report],
  );
  const aiPrompt = `Summarize my income statement from ${startDate} to ${endDate} in ${report?.currency ?? currency ?? "my base currency"}. Highlight key trends.`;

  const renderLineRow = (l: ReportLine) => {
    const openDrill = () =>
      report &&
      setDrillTarget({
        accountId: l.account_id,
        accountName: l.name,
        asOfDate: endDate,
        startDate,
        currency: report.currency,
      });
    return (
      <div key={l.account_id} className="flex justify-between gap-2 p-2 rounded-md bg-[var(--background-muted)] text-sm min-w-0">
        <span className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
          <button type="button" onClick={openDrill} className="truncate text-left hover:text-[var(--accent)] hover:underline">
            {l.name}
          </button>
          <ProvenanceBadge provenance={l.provenance} />
        </span>
        <button
          type="button"
          className="font-medium tabular-nums whitespace-nowrap shrink-0 underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
          onClick={openDrill}
          aria-label={`View source transactions for ${l.name}`}
        >
          {report ? formatCurrencyLocale(l.amount, report.currency) : "—"}
        </button>
      </div>
    );
  };

  return (
    <ReportPageShell
      title="Income Statement"
      description="Net Income = Income - Expenses"
      loadingLabel="Loading income statement"
      loadingSections={2}
      isLoading={!filters.ready || reportQuery.isLoading}
      isError={reportQuery.isError}
      errorMessage={reportQuery.error?.message}
      onRetry={() => void reportQuery.refetch()}
      toolbar={
        <ReportToolbar
          aiPrompt={aiPrompt}
          exportControl={<ExportCsvButton request={{ query: { report_type: "income-statement", format: "csv", start_date: startDate, end_date: endDate, currency } }} />}
        />
      }
    >
      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Account type</span>
          <select
            value={accountTypeFilter}
            onChange={(e) => setAccountTypeFilter(ACCOUNT_TYPE_OPTIONS.find((opt) => opt.value === e.target.value)?.value ?? "")}
            className="input w-auto"
          >
            {ACCOUNT_TYPE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-2 mb-6">
        <span className="text-xs text-muted uppercase">Tags</span>
        <div className="flex flex-wrap gap-2">
          {TAG_OPTIONS.map((tag) => (
            <button
              key={tag.value}
              onClick={() => toggleTag(tag.value)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                selectedTags.includes(tag.value) ? "bg-[var(--accent)] text-white" : "bg-[var(--background-muted)] text-muted hover:bg-[var(--background-muted)]/80"
              }`}
            >
              {tag.label}
            </button>
          ))}
          {selectedTags.length > 0 && (
            <button
              onClick={() => setSelectedTags([])}
              className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--error-muted)] text-[var(--error)] hover:bg-[var(--error-muted)]/80"
            >
              Clear all
            </button>
          )}
        </div>
      </div>

      <FxWarningBanner warnings={report?.fx_warnings} />

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <div className="card p-5">
          <p className="text-xs text-muted uppercase">Total Income</p>
          <p className="text-2xl font-semibold text-[var(--success)] mt-1">{report ? formatCurrencyLocale(report.total_income, report.currency) : "—"}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase">Total Expenses</p>
          <p className="text-2xl font-semibold text-[var(--error)] mt-1">{report ? formatCurrencyLocale(report.total_expenses, report.currency) : "—"}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-muted uppercase">Net Income</p>
          <p className="text-2xl font-semibold mt-1">{report ? formatCurrencyLocale(report.net_income, report.currency) : "—"}</p>
        </div>
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
          ) : (
            <p className="text-sm text-muted">No trend data yet.</p>
          )}
        </div>
        <div className="card p-5">
          <h3 className="font-semibold mb-3">Income</h3>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {report?.income?.length ? report.income.map(renderLineRow) : <p className="text-sm text-muted">No income categories.</p>}
          </div>
        </div>
      </div>

      <div className="card p-5">
        <h3 className="font-semibold mb-3">Expenses</h3>
        <div className="grid gap-2 md:grid-cols-2 max-h-96 overflow-y-auto">
          {report?.expenses?.length ? report.expenses.map(renderLineRow) : <p className="text-sm text-muted">No expense categories.</p>}
        </div>
      </div>

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}
