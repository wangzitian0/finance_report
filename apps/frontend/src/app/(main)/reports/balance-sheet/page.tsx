"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_URL, apiFetch } from "@/lib/api";
import { formatDateInput } from "@/lib/date";

interface ReportLine {
  account_id: string;
  name: string;
  type: string;
  parent_id?: string | null;
  amount: number | string;
}

interface BalanceSheetResponse {
  as_of_date: string;
  currency: string;
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets: number | string;
  total_liabilities: number | string;
  total_equity: number | string;
  equation_delta: number | string;
  is_balanced: boolean;
}

interface AccountNode extends ReportLine { children: AccountNode[]; }

const toNumber = (value: number | string): number => {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};
const formatCurrency = (currency: string, value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);

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
  const [report, setReport] = useState<BalanceSheetResponse | null>(null);
  const [asOfDate, setAsOfDate] = useState(() => formatDateInput(new Date()));
  const [currency, setCurrency] = useState("SGD");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<BalanceSheetResponse>(`/api/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}`);
      setReport(data);
      setError(null);
      const rootIds = new Set<string>();
      [...data.assets, ...data.liabilities, ...data.equity].forEach((l) => { if (!l.parent_id) rootIds.add(l.account_id); });
      setExpanded(rootIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load balance sheet.");
    } finally { setLoading(false); }
  }, [asOfDate, currency]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const assetsTree = useMemo(() => report ? buildTree(report.assets) : [], [report]);
  const liabilitiesTree = useMemo(() => report ? buildTree(report.liabilities) : [], [report]);
  const equityTree = useMemo(() => report ? buildTree(report.equity) : [], [report]);

  const exportUrl = `${API_URL}/api/reports/export?report_type=balance-sheet&format=csv&as_of_date=${asOfDate}&currency=${currency}`;
  const aiPrompt = useMemo(() => encodeURIComponent(`Explain my balance sheet as of ${asOfDate} in ${currency}. Highlight any risks.`), [asOfDate, currency]);

  const toggle = (id: string) => setExpanded((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });

  const renderNode = (node: AccountNode, depth = 0) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expanded.has(node.account_id);
    return (
      <div key={node.account_id}>
        <div className="flex items-center justify-between px-3 py-2 text-sm rounded-md hover:bg-[var(--background-muted)]/50" style={{ paddingLeft: depth * 16 + 12 }}>
          <div className="flex items-center gap-2">
            {hasChildren && <button onClick={() => toggle(node.account_id)} className="w-5 h-5 rounded-md bg-[var(--background-muted)] text-xs flex items-center justify-center">{isExpanded ? "–" : "+"}</button>}
            <span>{node.name}</span>
          </div>
          <span className="font-medium">{report ? formatCurrency(report.currency, toNumber(node.amount)) : "—"}</span>
        </div>
        {hasChildren && isExpanded && <div className="ml-2 border-l border-[var(--border)] pl-2">{node.children.map((c) => renderNode(c, depth + 1))}</div>}
      </div>
    );
  };

  if (loading) return <div className="p-6 flex items-center justify-center min-h-[60vh]"><span className="text-muted">Loading balance sheet...</span></div>;
  if (error) return (
    <div className="p-6"><div className="card p-8 text-center max-w-md mx-auto"><p className="text-muted mb-4">{error}</p><button onClick={fetchReport} className="btn-secondary">Retry</button></div></div>
  );

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Balance Sheet</h1>
          <p className="page-description">Assets = Liabilities + Equity</p>
        </div>
        <div className="flex gap-2">
          <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary text-sm">AI Interpretation</Link>
          <Link href="/dashboard" className="btn-secondary text-sm">Dashboard</Link>
          <a href={exportUrl} className="btn-secondary text-sm">Export CSV</a>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-6 text-sm">
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">As of date</span><input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} className="input w-auto" /></label>
        <label className="flex flex-col gap-1"><span className="text-xs text-muted uppercase">Currency</span><select value={currency} onChange={(e) => setCurrency(e.target.value)} className="input w-auto"><option value="SGD">SGD</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
        <span className={`self-end badge ${report?.is_balanced ? "badge-success" : "badge-warning"}`}>{report?.is_balanced ? "✓ Balanced" : "⚠ Drift"}</span>
      </div>

      <div className="flex flex-col gap-2 mb-6">
        <span className="text-xs text-muted uppercase">Quick filters</span>
        <div className="flex flex-wrap gap-2">
          <Link href="/reports/balance-sheet" className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--accent)] text-white">All</Link>
          <Link href="/reports/balance-sheet#assets" className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--success-muted)] hover:text-[var(--success)]">Assets</Link>
          <Link href="/reports/balance-sheet#liabilities" className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--error-muted)] hover:text-[var(--error)]">Liabilities</Link>
          <Link href="/reports/balance-sheet#equity" className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--background-muted)] text-muted hover:bg-[var(--accent-muted)] hover:text-[var(--accent)]">Equity</Link>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-5">
          <h2 className="font-semibold mb-3">Assets</h2>
          <div className="space-y-1">{assetsTree.length ? assetsTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--success)]">Total: {report ? formatCurrency(report.currency, toNumber(report.total_assets)) : "—"}</div>
        </div>
        <div className="card p-5">
          <h2 className="font-semibold mb-3">Liabilities</h2>
          <div className="space-y-1">{liabilitiesTree.length ? liabilitiesTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold text-[var(--error)]">Total: {report ? formatCurrency(report.currency, toNumber(report.total_liabilities)) : "—"}</div>
        </div>
        <div className="card p-5">
          <h2 className="font-semibold mb-3">Equity</h2>
          <div className="space-y-1">{equityTree.length ? equityTree.map((n) => renderNode(n)) : <span className="text-muted">—</span>}</div>
          <div className="mt-4 pt-3 border-t border-[var(--border)] font-semibold">Total: {report ? formatCurrency(report.currency, toNumber(report.total_equity)) : "—"}</div>
        </div>
      </div>
    </div>
  );
}
