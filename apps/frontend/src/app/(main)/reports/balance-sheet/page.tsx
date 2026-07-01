"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";

import { formatCurrencyLocale } from "@/lib/audit/money";
import { useCurrencies } from "@/hooks/useCurrencies";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useReportFilters } from "@/hooks/useReportFilters";
import { FxWarningBanner } from "@/components/reports/FxWarningBanner";
import { OpeningBalanceWarningBanner } from "@/components/reports/OpeningBalanceWarningBanner";
import ConfidenceBadge, { type ConfidenceTier } from "@/components/ui/ConfidenceBadge";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ReportPageShell } from "@/components/reports/ReportPageShell";
import { ReportToolbar } from "@/components/reports/ReportToolbar";
import { ExportCsvButton } from "@/components/reports/ExportCsvButton";
import { CurrencyFilterControl, DateFilterControl } from "@/components/reports/ReportFilters";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { InfoHint } from "@/components/ui/InfoHint";
import type { BalanceSheetResponse, ReportLine } from "@/lib/types";

interface AccountNode extends ReportLine { children: AccountNode[]; }

const buildTree = (lines: ReportLine[]): AccountNode[] => {
  const nodes = new Map<string, AccountNode>();
  lines.forEach((line) => nodes.set(line.account_id, { ...line, children: [] }));
  const roots: AccountNode[] = [];
  nodes.forEach((node) => {
    if (node.parent_id && nodes.has(node.parent_id)) nodes.get(node.parent_id)?.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (items: AccountNode[]) => { items.sort((a, b) => a.name.localeCompare(b.name)); items.forEach((item) => sortNodes(item.children)); };
  sortNodes(roots);
  return roots;
};

export default function BalanceSheetPage() {
  const { asOfDate, setAsOfDate, currency, setCurrency } = useReportFilters({
    reportType: "balance-sheet",
  });
  const searchParams = useSearchParams();
  const includeRestrictedParam = searchParams.get("include_restricted");
  const [includeRestricted, setIncludeRestricted] = useState(includeRestrictedParam === "true");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);
  const { currencies } = useCurrencies();

  // Balance sheet adds the restricted-holdings toggle on top of the shared
  // date/currency filters, so it builds its own request query string here.
  const queryString = useMemo(() => {
    const params = new URLSearchParams({
      as_of_date: asOfDate,
      currency,
      include_restricted: includeRestricted ? "true" : "false",
    });
    return params.toString();
  }, [asOfDate, currency, includeRestricted]);
  const reportQuery = useApiQuery<BalanceSheetResponse>(
    ["report", "balance-sheet", queryString],
    `/api/reports/balance-sheet?${queryString}`,
    { placeholderData: keepPreviousData },
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

  const assetsTree = useMemo(() => report ? buildTree(report.assets) : [], [report]);
  const liabilitiesTree = useMemo(() => report ? buildTree(report.liabilities) : [], [report]);
  const equityTree = useMemo(() => report ? buildTree(report.equity) : [], [report]);

  const exportPath = `/api/reports/export?report_type=balance-sheet&format=csv&${queryString}`;
  const aiPrompt = useMemo(() => `Explain my balance sheet as of ${asOfDate} in ${currency}. Highlight any risks.`, [asOfDate, currency]);

  useEffect(() => {
    setIncludeRestricted(includeRestrictedParam === "true");
  }, [includeRestrictedParam]);

  const toggle = (id: string) => setExpanded((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });

  const renderNode = (node: AccountNode, depth = 0) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expanded.has(node.account_id);
    return (
      <div key={node.account_id} role="treeitem" aria-level={depth + 1} aria-selected={false} aria-expanded={hasChildren ? isExpanded : undefined}>
        <div className="flex items-center justify-between px-3 py-2 text-sm rounded-md hover:bg-[var(--background-muted)]/50" style={{ paddingLeft: depth * 16 + 12 }}>
          <div className="flex items-center gap-2">
            {hasChildren && <button onClick={() => toggle(node.account_id)} className="w-5 h-5 rounded-md bg-[var(--background-muted)] text-xs flex items-center justify-center">{isExpanded ? "–" : "+"}</button>}
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
        {hasChildren && isExpanded && <div role="group" className="ml-2 border-l border-[var(--border)] pl-2">{node.children.map((c) => renderNode(c, depth + 1))}</div>}
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
          exportControl={<ExportCsvButton path={exportPath} />}
        />
      }
    >
      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <DateFilterControl label="As of date" value={asOfDate} onChange={setAsOfDate} />
        <CurrencyFilterControl value={currency} currencies={currencies} onChange={setCurrency} />
        <label className="self-end flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-2">
          <input type="checkbox" checked={includeRestricted} onChange={(e) => setIncludeRestricted(e.target.checked)} />
          <span>Include restricted holdings</span>
        </label>
        <span className="self-end inline-flex items-center"><span className={`badge ${report?.is_balanced ? "badge-success" : "badge-warning"}`}>{report?.is_balanced ? "✓ Balanced" : "⚠ Drift"}</span><InfoHint term={report?.is_balanced ? "balanced" : "drift"} label={report?.is_balanced ? "Balanced" : "Drift"} /></span>
        {report?.confidence_tier ? (
          <span className="self-end inline-flex items-center" title="Aggregate confidence of these totals">
            <ConfidenceBadge tier={report.confidence_tier as ConfidenceTier} />
          </span>
        ) : null}
      </div>

      <FxWarningBanner warnings={report?.fx_warnings} />
      <OpeningBalanceWarningBanner warnings={report?.opening_balance_warnings} />

      <div className="flex flex-col gap-2 mb-6">
        <span className="text-xs text-muted uppercase">Quick filters</span>
        <div className="flex flex-wrap gap-2">
          <Link href={`/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}`} className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--accent)] text-white">All</Link>
          <Link href={`/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}#assets`} className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--success-muted)] hover:text-[var(--success)]">Assets</Link>
          <Link href={`/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}#liabilities`} className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--error-muted)] hover:text-[var(--error)]">Liabilities</Link>
          <Link href={`/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}#equity`} className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--accent-muted)] hover:text-[var(--accent)]">Equity</Link>
        </div>
      </div>

      <div className="card p-5 mb-6">
        <h2 className="font-semibold mb-3">Balance Equation Detail</h2>
        <dl className="grid gap-3 text-sm md:grid-cols-5">
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

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-5" id="assets">
          <h2 className="font-semibold mb-3">Assets</h2>
          <div role="tree" aria-label="Balance Sheet - Assets" className="space-y-1">{assetsTree.length ? assetsTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--success)]">Total: {report ? formatCurrencyLocale(report.total_assets, report.currency) : "—"}</div>
        </div>
        <div className="card p-5" id="liabilities">
          <h2 className="font-semibold mb-3">Liabilities</h2>
          <div role="tree" aria-label="Balance Sheet - Liabilities" className="space-y-1">{liabilitiesTree.length ? liabilitiesTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--error)]">Total: {report ? formatCurrencyLocale(report.total_liabilities, report.currency) : "—"}</div>
        </div>
        <div className="card p-5" id="equity">
          <h2 className="font-semibold mb-3">Equity</h2>
          <div role="tree" aria-label="Balance Sheet - Equity" className="space-y-1">{equityTree.length ? equityTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold">Total: {report ? formatCurrencyLocale(report.total_equity, report.currency) : "—"}</div>
        </div>
      </div>

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}
