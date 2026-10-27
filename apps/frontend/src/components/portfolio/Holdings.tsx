"use client";

import Link from "next/link";
import { PortfolioHolding, PriceUpdate } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatQuantity } from "@/lib/audit/quantity";
import { formatDateDisplay } from "@/lib/date";
import { formatSignedPercentFromPercentValue } from "@/lib/audit/ratio/format";
import { pnlColorClass } from "@/lib/statusLabels";
import { portfolioHoldingHref } from "@/components/navigation";
import { ProvenanceBadge } from "@/components/ui";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiOperation } from "@/lib/api-client";
import { useToast } from "@/components/ui/Toast";

interface HoldingsTableProps {
  holdings: PortfolioHolding[];
  showDisposed?: boolean;
}

export function HoldingsTable({
  holdings,
  showDisposed = false,
}: HoldingsTableProps) {
  const filtered = showDisposed
    ? holdings
    : holdings.filter((h) => h.status === "active");

  if (filtered.length === 0) {
    return (
      <div className="card p-8 text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--background-muted)] text-muted mb-4">
          <svg
            className="w-6 h-6"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
            />
          </svg>
        </div>
        <p className="text-muted">No holdings found</p>
        <p className="text-sm text-muted mt-1">
          Upload brokerage statements and reconcile to see holdings.
        </p>
      </div>
    );
  }

  // Group by broker/account
  const grouped = filtered.reduce(
    (groups, h) => {
      const key = h.account_name ?? "Unknown";
      if (!groups[key]) groups[key] = [];
      groups[key].push(h);
      return groups;
    },
    {} as Record<string, PortfolioHolding[]>,
  );

  return (
    <div className="space-y-4">
      {Object.entries(grouped).map(([broker, brokerHoldings]) => (
        <div key={broker} className="card">
          <div className="card-header flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="badge badge-primary">{broker}</span>
              <span className="text-xs text-muted">
                {brokerHoldings.length} holdings
              </span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left px-4 py-2 font-medium">Asset</th>
                  <th className="text-right px-4 py-2 font-medium">Qty</th>
                  <th className="text-right px-4 py-2 font-medium">
                    Cost Basis
                  </th>
                  <th className="text-right px-4 py-2 font-medium">
                    Market Value
                  </th>
                  <th className="text-right px-4 py-2 font-medium">P&L</th>
                  <th className="text-right px-4 py-2 font-medium">P&L %</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {brokerHoldings.map((h) => (
                  <tr
                    key={h.id}
                    className="hover:bg-[var(--background-muted)]/50 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <Link
                          href={portfolioHoldingHref(h.asset_identifier)}
                          className="font-medium font-mono text-[var(--accent)] hover:underline"
                        >
                          {h.asset_identifier}
                        </Link>
                        <ProvenanceBadge provenance={h.provenance} />
                      </span>
                      <div className="text-xs text-muted mt-0.5">
                        {formatDateDisplay(h.acquisition_date)}
                        {h.sector && ` · ${h.sector}`}
                        {/* #1487: a foreign holding's values below are shown in
                            the reporting currency — surface its native currency
                            so the denomination is never hidden. */}
                        {h.native_currency && h.native_currency !== h.currency && (
                          <span title={`Denominated in ${h.native_currency}; values shown in ${h.currency}`}>
                            {` · ${h.native_currency}-denominated`}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {formatQuantity(h.quantity)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {formatCurrencyLocale(h.cost_basis, h.currency)}
                    </td>
                    <td className="px-4 py-2 text-right font-medium">
                      {formatCurrencyLocale(h.market_value, h.currency)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-medium ${pnlColorClass(h.unrealized_pnl)}`}
                    >
                      {formatCurrencyLocale(h.unrealized_pnl, h.currency)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right ${pnlColorClass(h.unrealized_pnl_percent)}`}
                    >
                      {formatSignedPercentFromPercentValue(
                        h.unrealized_pnl_percent,
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`badge ${h.status === "active" ? "badge-success" : "badge-muted"}`}
                      >
                        {h.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

// The body of the holding drawer that `/portfolio?ticker=` opens.
export function HoldingDetail({ ticker }: { ticker: string }) {
  const [activeTab, setActiveTab] = useState<"overview" | "dividends" | "realized">("overview");
  const [savingMethod, setSavingMethod] = useState(false);

  const { data: allHoldings, isLoading, error, refetch } = useQuery({
    queryKey: ["portfolio-holdings-all"],
    queryFn: () => apiOperation("get_holdings_portfolio_holdings_get", { query: { include_disposed: true } }).then((r) => r.items),
  });
  const { data: dividends = [], refetch: refetchDividends } = useQuery({
    queryKey: ["portfolio-dividends", ticker],
    queryFn: () => apiOperation("get_holding_dividends_portfolio__ticker__dividends_get", { path: { ticker } }),
  });
  const { data: realizedLots = [], refetch: refetchRealized } = useQuery({
    queryKey: ["portfolio-realized", ticker],
    queryFn: () => apiOperation("get_holding_realized_lots_portfolio__ticker__realized_get", { path: { ticker } }),
  });

  const holdings = allHoldings?.filter((h) => h.asset_identifier === ticker) ?? [];
  const activeHoldings = holdings.filter((h) => h.status === "active");
  const disposedHoldings = holdings.filter((h) => h.status === "disposed");

  if (isLoading) {
    return (
      <div className="card p-8 text-center text-muted">
        <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
        <p className="text-sm">Loading holding details...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-8 text-center" role="alert" aria-live="polite">
        <p className="text-[var(--foreground)] font-medium mb-2">Failed to load holding</p>
        <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
        <button onClick={() => refetch()} className="btn-secondary">Retry</button>
      </div>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="card p-8 text-center">
        <p className="text-muted">No holdings found for <span className="font-mono font-medium">{ticker}</span></p>
      </div>
    );
  }

  const primary = activeHoldings[0] ?? holdings[0];
  const selectedCostBasisMethod = primary.cost_basis_method ?? "FIFO";

  const updateCostBasisMethod = async (method: "FIFO" | "LIFO" | "AvgCost") => {
    setSavingMethod(true);
    try {
      await apiOperation("update_holding_cost_basis_method_portfolio__ticker__patch", {
        path: { ticker },
        body: { cost_basis_method: method },
      });
      await Promise.all([refetch(), refetchRealized(), refetchDividends()]);
    } finally {
      setSavingMethod(false);
    }
  };

  return (
    <div>
      <p className="mb-4 text-sm text-muted">
        {primary.sector && `${primary.sector} · `}
        {primary.geography && `${primary.geography} · `}
        {primary.asset_type ?? "Equity"}
      </p>

      <div className="mb-6 flex flex-col gap-3 border-b border-[var(--border)] pb-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-2" role="tablist" aria-label="Holding detail views">
          {([["overview", "Overview"], ["dividends", "Dividends"], ["realized", "Realized P&L"]] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={activeTab === value}
              onClick={() => setActiveTab(value)}
              className={`inline-flex min-h-[44px] items-center rounded border px-3 py-2.5 text-sm ${activeTab === value ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-muted"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-muted">
          <span>Cost basis method</span>
          <select
            value={selectedCostBasisMethod}
            disabled={savingMethod}
            onChange={(e) => updateCostBasisMethod(e.target.value as "FIFO" | "LIFO" | "AvgCost")}
            className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)]"
          >
            <option value="FIFO">FIFO</option>
            <option value="LIFO">LIFO</option>
            <option value="AvgCost">AvgCost</option>
          </select>
        </label>
      </div>

      {activeTab === "overview" && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 mb-6">
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Market Value</p>
              <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(primary.market_value, primary.currency)}</p>
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Cost Basis</p>
              <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(primary.cost_basis, primary.currency)}</p>
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Unrealized P&L</p>
              <p className={`text-2xl font-semibold mt-1 ${pnlColorClass(primary.unrealized_pnl)}`}>
                {formatCurrencyLocale(primary.unrealized_pnl, primary.currency)}
              </p>
              <p className={`text-sm mt-0.5 ${pnlColorClass(primary.unrealized_pnl_percent)}`}>
                {formatSignedPercentFromPercentValue(primary.unrealized_pnl_percent)}
              </p>
            </div>
            <div className="card p-5">
              <p className="text-xs text-muted uppercase tracking-wide">Quantity</p>
              <p className="text-2xl font-semibold mt-1 font-mono">{formatQuantity(primary.quantity)}</p>
              <p className="text-xs text-muted mt-0.5">{primary.cost_basis_method ?? "Default"} method</p>
            </div>
          </div>

          {activeHoldings.length > 0 && (
            <div className="card mb-6">
              <div className="card-header"><h2 className="text-sm font-medium">Active Lots</h2></div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      <th className="text-left px-4 py-2 font-medium">Account</th>
                      <th className="text-right px-4 py-2 font-medium">Qty</th>
                      <th className="text-right px-4 py-2 font-medium">Cost Basis</th>
                      <th className="text-right px-4 py-2 font-medium">Market Value</th>
                      <th className="text-right px-4 py-2 font-medium">P&L</th>
                      <th className="text-left px-4 py-2 font-medium">Acquired</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {activeHoldings.map((h) => (
                      <tr key={h.id} className="hover:bg-[var(--background-muted)]/50">
                        <td className="px-4 py-2">{h.account_name ?? "Unknown"}</td>
                        <td className="px-4 py-2 text-right font-mono">{formatQuantity(h.quantity)}</td>
                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(h.cost_basis, h.currency)}</td>
                        <td className="px-4 py-2 text-right font-medium">{formatCurrencyLocale(h.market_value, h.currency)}</td>
                        <td className={`px-4 py-2 text-right font-medium ${pnlColorClass(h.unrealized_pnl)}`}>
                          {formatCurrencyLocale(h.unrealized_pnl, h.currency)}
                        </td>
                        <td className="px-4 py-2">{formatDateDisplay(h.acquisition_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {disposedHoldings.length > 0 && (
            <div className="card">
              <div className="card-header"><h2 className="text-sm font-medium">Disposed Lots</h2></div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      <th className="text-left px-4 py-2 font-medium">Account</th>
                      <th className="text-right px-4 py-2 font-medium">Qty</th>
                      <th className="text-right px-4 py-2 font-medium">Cost Basis</th>
                      <th className="text-left px-4 py-2 font-medium">Acquired</th>
                      <th className="text-left px-4 py-2 font-medium">Disposed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {disposedHoldings.map((h) => (
                      <tr key={h.id} className="hover:bg-[var(--background-muted)]/50 text-muted">
                        <td className="px-4 py-2">{h.account_name ?? "Unknown"}</td>
                        <td className="px-4 py-2 text-right font-mono">{formatQuantity(h.quantity)}</td>
                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(h.cost_basis, h.currency)}</td>
                        <td className="px-4 py-2">{formatDateDisplay(h.acquisition_date)}</td>
                        <td className="px-4 py-2">{h.disposal_date ? formatDateDisplay(h.disposal_date) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {activeTab === "dividends" && (
        <div className="card">
          <div className="card-header"><h2 className="text-sm font-medium">Dividend Events</h2></div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left px-4 py-2 font-medium">Ex Date</th>
                  <th className="text-left px-4 py-2 font-medium">Pay Date</th>
                  <th className="text-right px-4 py-2 font-medium">Amount</th>
                  <th className="text-left px-4 py-2 font-medium">Currency</th>
                  <th className="text-left px-4 py-2 font-medium">Reinvested</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {dividends.length ? (
                  dividends.map((event) => (
                    <tr key={event.id}>
                      <td className="px-4 py-2">{formatDateDisplay(event.ex_date)}</td>
                      <td className="px-4 py-2">{formatDateDisplay(event.pay_date)}</td>
                      <td className="px-4 py-2 text-right">{formatCurrencyLocale(event.amount, event.currency)}</td>
                      <td className="px-4 py-2">{event.currency}</td>
                      <td className="px-4 py-2">{event.reinvested ? "Yes" : "No"}</td>
                    </tr>
                  ))
                ) : (
                  <tr><td className="px-4 py-6 text-center text-muted" colSpan={5}>No dividends recorded.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "realized" && (
        <div className="card">
          <div className="card-header"><h2 className="text-sm font-medium">Realized P&L Lots</h2></div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left px-4 py-2 font-medium">Lot</th>
                  <th className="text-left px-4 py-2 font-medium">Acquired</th>
                  <th className="text-left px-4 py-2 font-medium">Sold</th>
                  <th className="text-right px-4 py-2 font-medium">Quantity</th>
                  <th className="text-right px-4 py-2 font-medium">Basis</th>
                  <th className="text-right px-4 py-2 font-medium">Proceeds</th>
                  <th className="text-right px-4 py-2 font-medium">Gain/Loss</th>
                  <th className="text-right px-4 py-2 font-medium">Holding Period</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {realizedLots.length ? (
                  realizedLots.map((lot) => (
                    <tr key={lot.lot_id}>
                      <td className="px-4 py-2 font-mono">{lot.lot_id.slice(0, 8)}</td>
                      <td className="px-4 py-2">{lot.acquired_date ? formatDateDisplay(lot.acquired_date) : "—"}</td>
                      <td className="px-4 py-2">{formatDateDisplay(lot.sold_date)}</td>
                      <td className="px-4 py-2 text-right font-mono">{formatQuantity(lot.quantity)}</td>
                      <td className="px-4 py-2 text-right">{formatCurrencyLocale(lot.basis, lot.currency)}</td>
                      <td className="px-4 py-2 text-right">{formatCurrencyLocale(lot.proceeds, lot.currency)}</td>
                      <td className={`px-4 py-2 text-right font-medium ${pnlColorClass(lot.gain_loss)}`}>
                        {formatCurrencyLocale(lot.gain_loss, lot.currency)}
                      </td>
                      <td className="px-4 py-2 text-right">{lot.holding_period ?? "—"}</td>
                    </tr>
                  ))
                ) : (
                  <tr><td className="px-4 py-6 text-center text-muted" colSpan={8}>No realized lots recorded.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

interface PriceRow {
  asset_identifier: string;
  price: string;
  currency: string;
  price_date: string;
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_ROW: PriceRow = {
  asset_identifier: "",
  price: "",
  currency: "USD",
  price_date: todayStr(),
};

interface PriceUpdateFormProps {
  /** Pre-filled tickers from holdings, so user can pick from them */
  knownTickers?: string[];
  onSuccess?: () => void;
}

export function PriceUpdateForm({
  knownTickers = [],
  onSuccess,
}: PriceUpdateFormProps) {
  const { showToast } = useToast();
  const [rows, setRows] = useState<PriceRow[]>([{ ...EMPTY_ROW }]);

  const mutation = useMutation({
    mutationFn: (updates: PriceUpdate[]) =>
      apiOperation("update_prices_portfolio_prices_update_post", {
        body: { updates },
      }),
    onSuccess: (result) => {
      showToast(`Updated ${result.updated_count} price(s)`, "success");
      setRows([{ ...EMPTY_ROW }]);
      onSuccess?.();
    },
    onError: (err: Error) => {
      showToast(`Failed: ${err.message}`, "error");
    },
  });

  const updateRow = (index: number, field: keyof PriceRow, value: string) => {
    setRows((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addRow = () => setRows((prev) => [...prev, { ...EMPTY_ROW }]);

  const removeRow = (index: number) => {
    setRows((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index),
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const valid = rows.filter(
      (r) => r.asset_identifier.trim() && r.price.trim(),
    );
    if (valid.length === 0) {
      showToast("Add at least one price update", "error");
      return;
    }

    const updates: PriceUpdate[] = valid.map((r) => ({
      asset_identifier: r.asset_identifier.trim(),
      price: r.price.trim(),
      currency: r.currency.trim() || "USD",
      price_date: r.price_date,
    }));

    mutation.mutate(updates);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-3">
        {rows.map((row, index) => (
          <div key={index} className="flex items-end gap-3">
            <div className="flex-1">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Ticker / Asset" : ""}
              </label>
              {knownTickers.length > 0 ? (
                <select
                  value={row.asset_identifier}
                  onChange={(e) =>
                    updateRow(index, "asset_identifier", e.target.value)
                  }
                  className="input"
                  required
                >
                  <option value="">Select asset...</option>
                  {knownTickers.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={row.asset_identifier}
                  onChange={(e) =>
                    updateRow(index, "asset_identifier", e.target.value)
                  }
                  placeholder="AAPL, MSFT..."
                  className="input"
                  required
                />
              )}
            </div>
            <div className="w-32">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Price" : ""}
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={row.price}
                onChange={(e) => updateRow(index, "price", e.target.value)}
                placeholder="0.00"
                className="input"
                required
              />
            </div>
            <div className="w-20">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "CCY" : ""}
              </label>
              <input
                type="text"
                maxLength={3}
                value={row.currency}
                onChange={(e) =>
                  updateRow(index, "currency", e.target.value.toUpperCase())
                }
                className="input uppercase"
                required
              />
            </div>
            <div className="w-36">
              <label className="block text-xs text-muted mb-1">
                {index === 0 ? "Date" : ""}
              </label>
              <input
                type="date"
                value={row.price_date}
                onChange={(e) => updateRow(index, "price_date", e.target.value)}
                className="input"
                required
              />
            </div>
            <button
              type="button"
              onClick={() => removeRow(index)}
              className="p-2 text-muted hover:text-[var(--error)] transition-colors"
              aria-label="Remove row"
              disabled={rows.length <= 1}
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={addRow}
          className="btn-ghost text-sm flex items-center gap-1"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 4v16m8-8H4"
            />
          </svg>
          Add Row
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="btn-primary flex items-center gap-2"
        >
          {mutation.isPending && (
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          )}
          Update Prices
        </button>
      </div>
    </form>
  );
}
