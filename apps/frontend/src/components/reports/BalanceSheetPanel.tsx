"use client";

import { useEffect, useMemo, useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";

import { formatCurrencyLocale, sumAmounts, toDecimal } from "@/lib/audit/money";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { ReportFilters } from "@/hooks/useReportFilters";
import { balanceSheetQueryKey } from "@/lib/sharedQueries";
import { NetWorthTimeSeriesChart } from "@/components/charts/NetWorthTimeSeriesChart";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import {
  ExportCsvButton,
  FxWarningBanner,
  OpeningBalanceWarningBanner,
  ReportPageShell,
  ReportToolbar,
} from "@/components/reports/ReportPageShell";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { InfoHint } from "@/components/ui/InfoHint";
import { liabilityToneClass } from "@/lib/statusLabels";
import { normalizeFxWarningRows, type ReportLine } from "@/lib/types";

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
  const adjustments = report
    ? sumAmounts([report.unrealized_fx_gain_loss ?? 0, report.cta_adjustment ?? 0, report.net_worth_adjustment_gain_loss ?? 0])
    : null;
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
    return (
      <div
        key={node.account_id}
        role="treeitem"
        aria-level={depth + 1}
        aria-selected={false}
        aria-expanded={hasChildren ? isExpanded : undefined}
      >
        <div
          className="flex items-center justify-between px-3 py-2 text-sm rounded-md hover:bg-[var(--background-muted)]/50"
          style={{ paddingLeft: depth * 16 + 12 }}
        >
          <div className="flex items-center gap-2">
            {hasChildren && (
              <button
                onClick={() => toggle(node.account_id)}
                aria-label={isExpanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
                className="-my-2 flex h-11 w-11 items-center justify-center text-base leading-none text-[var(--foreground-muted)] hover:text-[var(--foreground)]"
              >
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[var(--background-muted)] text-xs" aria-hidden="true">
                  {isExpanded ? "–" : "+"}
                </span>
              </button>
            )}
            <span>{node.name}</span>
            <ProvenanceBadge provenance={node.provenance} />
          </div>
          {report ? (
            <button
              type="button"
              className="font-medium tabular-nums hover:text-[var(--accent)] hover:underline"
              onClick={() => setDrillTarget({ accountId: node.account_id, accountName: node.name, asOfDate, currency: report.currency })}
              aria-label={`View source transactions for ${node.name}`}
            >
              {formatCurrencyLocale(node.amount, report.currency)}
            </button>
          ) : (
            <span className="font-medium">—</span>
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

      <details className="card mb-6 group" data-testid="balance-equation-detail">
        <summary className="p-4 font-semibold cursor-pointer list-none flex items-center justify-between hover:bg-[var(--background-muted)] rounded-lg transition-colors select-none">
          <span className="flex items-center gap-2">
            <span>Balance Equation Detail</span>
            <span className="text-xs font-normal text-muted">
              {report?.is_balanced ? "Books in balance" : report ? `Delta: ${formatCurrencyLocale(report.equation_delta, report.currency)}` : "—"}
            </span>
          </span>
          <span className="text-xs text-muted group-open:rotate-180 transition-transform">▼</span>
        </summary>
        <div className="p-5 pt-1 border-t border-[var(--border)]">
          <dl className="grid gap-3 text-sm grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            <div>
              <dt className="text-xs text-muted uppercase">Net Income</dt>
              <dd className="mt-1 font-medium">{report ? formatCurrencyLocale(report.net_income ?? 0, report.currency) : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted uppercase">Unrealized FX</dt>
              <dd className="mt-1 font-medium">{report ? formatCurrencyLocale(report.unrealized_fx_gain_loss ?? 0, report.currency) : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted uppercase">Net Worth Adjustment</dt>
              <dd className="mt-1 font-medium">{report ? formatCurrencyLocale(report.net_worth_adjustment_gain_loss ?? 0, report.currency) : "—"}</dd>
            </div>
            <div data-testid="equation-detail-cta">
              <dt className="text-xs text-muted uppercase">CTA Adjustment</dt>
              <dd className="mt-1 font-medium" aria-label="Currency translation adjustment">
                {report ? formatCurrencyLocale(report.cta_adjustment ?? "0.00", report.currency) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted uppercase">Equation Delta</dt>
              <dd className="mt-1 font-medium">{report ? formatCurrencyLocale(report.equation_delta, report.currency) : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted uppercase">Restricted Treatment</dt>
              <dd className="mt-1 font-medium">{includeRestricted ? "Included" : "Excluded by default"}</dd>
            </div>
          </dl>
        </div>
      </details>

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <div className="card p-5" id="assets">
          <h2 className="font-semibold mb-3">Assets</h2>
          <div role="tree" aria-label="Balance Sheet - Assets" className="space-y-1">
            {assetsTree.length ? assetsTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--success)]">
            Total: {report ? formatCurrencyLocale(report.total_assets, report.currency) : "—"}
          </div>
        </div>
        <div className="card p-5" id="liabilities">
          <h2 className="font-semibold mb-3">Liabilities</h2>
          <div role="tree" aria-label="Balance Sheet - Liabilities" className="space-y-1">
            {liabilitiesTree.length ? liabilitiesTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className={`mt-4 pt-3 border-t border-[var(--border)] font-semibold ${report ? liabilityToneClass(report.total_liabilities) : "text-muted"}`}>
            Total: {report ? formatCurrencyLocale(report.total_liabilities, report.currency) : "—"}
          </div>
        </div>
        <div className="card p-5" id="equity">
          <h2 className="font-semibold mb-3">Equity</h2>
          <div role="tree" aria-label="Balance Sheet - Equity" className="space-y-1">
            {equityTree.length ? equityTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}
          </div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] space-y-1 text-sm">
            <div className="flex justify-between text-muted">
              <span>Opening Equity:</span>
              <span>{report ? formatCurrencyLocale(report.total_equity, report.currency) : "—"}</span>
            </div>
            <div className="flex justify-between text-muted">
              <span>Net Income (P&L):</span>
              <span className={report && toDecimal(report.net_income ?? 0).isNegative() ? "text-[var(--error)] font-medium" : "text-[var(--success)] font-medium"}>
                {report ? formatCurrencyLocale(report.net_income ?? 0, report.currency) : "—"}
              </span>
            </div>
            {report && adjustments && !adjustments.isZero() && (
              <div className="flex justify-between text-muted">
                <span>Adjustments (FX/CTA):</span>
                <span>{formatCurrencyLocale(adjustments, report.currency)}</span>
              </div>
            )}
            <div className="pt-2 border-t border-[var(--border)] font-semibold flex justify-between">
              <span>Total:</span>
              <span>
                {report && adjustments
                  ? formatCurrencyLocale(sumAmounts([report.total_equity, report.net_income ?? 0, adjustments]), report.currency)
                  : "—"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <NetWorthTimeSeriesChart from={startDate} to={asOfDate} currency={currency} />

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}
