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

interface AccountNode extends ReportLine {
  children: AccountNode[];
}

const toNumber = (value: number | string) =>
  typeof value === "string" ? Number(value) : value;

const formatCurrency = (currency: string, value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);

const buildTree = (lines: ReportLine[]): AccountNode[] => {
  const nodes = new Map<string, AccountNode>();
  lines.forEach((line) => nodes.set(line.account_id, { ...line, children: [] }));

  const roots: AccountNode[] = [];
  nodes.forEach((node) => {
    if (node.parent_id && nodes.has(node.parent_id)) {
      nodes.get(node.parent_id)?.children.push(node);
    } else {
      roots.push(node);
    }
  });

  const sortNodes = (items: AccountNode[]) => {
    items.sort((a, b) => a.name.localeCompare(b.name));
    items.forEach((item) => sortNodes(item.children));
  };
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
      const data = await apiFetch<BalanceSheetResponse>(
        `/api/reports/balance-sheet?as_of_date=${asOfDate}&currency=${currency}`
      );
      setReport(data);
      setError(null);
      const rootIds = new Set<string>();
      data.assets.forEach((line) => {
        if (!line.parent_id) rootIds.add(line.account_id);
      });
      data.liabilities.forEach((line) => {
        if (!line.parent_id) rootIds.add(line.account_id);
      });
      data.equity.forEach((line) => {
        if (!line.parent_id) rootIds.add(line.account_id);
      });
      setExpanded(rootIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load balance sheet.");
    } finally {
      setLoading(false);
    }
  }, [asOfDate, currency]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const assetsTree = useMemo(() => (report ? buildTree(report.assets) : []), [report]);
  const liabilitiesTree = useMemo(
    () => (report ? buildTree(report.liabilities) : []),
    [report]
  );
  const equityTree = useMemo(() => (report ? buildTree(report.equity) : []), [report]);

  const exportUrl = `${API_URL}/api/reports/export?report_type=balance-sheet&format=csv&as_of_date=${asOfDate}&currency=${currency}`;

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const renderNode = (node: AccountNode, depth = 0) => {
    const hasChildren = node.children.length > 0;
    const isExpanded = expanded.has(node.account_id);

    return (
      <div key={node.account_id}>
        <div
          className="flex items-center justify-between rounded-2xl px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          style={{ paddingLeft: `${depth * 16 + 12}px` }}
        >
          <div className="flex items-center gap-2">
            {hasChildren && (
              <button
                type="button"
                onClick={() => toggle(node.account_id)}
                className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 text-xs text-slate-500"
                aria-label={isExpanded ? "Collapse" : "Expand"}
              >
                {isExpanded ? "–" : "+"}
              </button>
            )}
            <span>{node.name}</span>
          </div>
          <span className="font-medium">
            {report ? formatCurrency(report.currency, toNumber(node.amount)) : "—"}
          </span>
        </div>
        {hasChildren && isExpanded && (
          <div className="ml-2 border-l border-slate-100 pl-2">
            {node.children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f8f4ed] flex items-center justify-center text-slate-600">
        Loading balance sheet…
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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f5f0e6_0%,#f6efe3_40%,#e7eceb_100%)] text-[#13201b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-16 right-[-3rem] h-56 w-56 rounded-full bg-[#ffe1b2] blur-3xl opacity-70"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-4rem] h-72 w-72 rounded-full bg-[#baf3e6] blur-3xl opacity-60"></div>

        <div className="relative z-10 mx-auto max-w-6xl px-6 py-10">
          <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.4em] text-emerald-700">
                Statement of Position
              </p>
              <h1 className="text-4xl font-semibold text-[#0f1f17]">Balance Sheet</h1>
              <p className="text-sm text-[#334136]">Assets = Liabilities + Equity</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/dashboard"
                className="rounded-full border border-emerald-200 bg-white/80 px-4 py-2 text-sm text-emerald-800"
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
              As of date
              <input
                type="date"
                value={asOfDate}
                onChange={(event) => setAsOfDate(event.target.value)}
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
            <span className="text-xs text-slate-500">
              {report?.is_balanced ? "Equation verified" : "Equation mismatch"}
            </span>
          </section>

          <section className="mt-10 grid gap-6 lg:grid-cols-3">
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-800">Assets</h2>
              <div className="mt-4 space-y-2">
                {assetsTree.length ? assetsTree.map((node) => renderNode(node)) : "—"}
              </div>
              <div className="mt-4 border-t border-slate-100 pt-4 text-sm font-semibold text-emerald-700">
                Total Assets: {report ? formatCurrency(report.currency, toNumber(report.total_assets)) : "—"}
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-800">Liabilities</h2>
              <div className="mt-4 space-y-2">
                {liabilitiesTree.length
                  ? liabilitiesTree.map((node) => renderNode(node))
                  : "—"}
              </div>
              <div className="mt-4 border-t border-slate-100 pt-4 text-sm font-semibold text-rose-600">
                Total Liabilities: {report ? formatCurrency(report.currency, toNumber(report.total_liabilities)) : "—"}
              </div>
            </div>
            <div className="rounded-3xl border border-white/40 bg-white/80 p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-800">Equity</h2>
              <div className="mt-4 space-y-2">
                {equityTree.length ? equityTree.map((node) => renderNode(node)) : "—"}
              </div>
              <div className="mt-4 border-t border-slate-100 pt-4 text-sm font-semibold text-slate-700">
                Total Equity: {report ? formatCurrency(report.currency, toNumber(report.total_equity)) : "—"}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
