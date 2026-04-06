"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { PortfolioHolding } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/currency";
import { formatDateDisplay } from "@/lib/date";

function formatQuantity(quantity: string): string {
    const num = parseFloat(quantity);
    if (Number.isInteger(num)) return num.toLocaleString();
    return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

function getPnlColor(value: string): string {
    const num = parseFloat(value);
    if (isNaN(num) || num === 0) return "";
    return num > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

function formatPnlPercent(value: string): string {
    const num = parseFloat(value);
    if (isNaN(num)) return "\u2014";
    const sign = num > 0 ? "+" : "";
    return `${sign}${num.toFixed(2)}%`;
}

export default function HoldingDetailPage() {
    const params = useParams();
    const ticker = decodeURIComponent(params.ticker as string);

    const { data: allHoldings, isLoading, error, refetch } = useQuery({
        queryKey: ["portfolio-holdings-all"],
        queryFn: () => apiFetch<PortfolioHolding[]>("/api/portfolio/holdings?include_disposed=true"),
    });

    const holdings = allHoldings?.filter((h) => h.asset_identifier === ticker) ?? [];
    const activeHoldings = holdings.filter((h) => h.status === "active");
    const disposedHoldings = holdings.filter((h) => h.status === "disposed");

    if (isLoading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading holding details...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-muted)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load holding</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <button onClick={() => refetch()} className="btn-secondary">Retry</button>
                </div>
            </div>
        );
    }

    if (holdings.length === 0) {
        return (
            <div className="p-6">
                <div className="mb-4">
                    <Link href="/portfolio" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                        </svg>
                        Back to Portfolio
                    </Link>
                </div>
                <div className="card p-8 text-center">
                    <p className="text-muted">No holdings found for <span className="font-mono font-medium">{ticker}</span></p>
                </div>
            </div>
        );
    }

    const primary = activeHoldings[0] ?? holdings[0];

    return (
        <div className="p-6">
            <div className="mb-4">
                <Link href="/portfolio" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Portfolio
                </Link>
            </div>

            <div className="page-header">
                <h1 className="page-title font-mono">{ticker}</h1>
                <p className="page-description">
                    {primary.sector && `${primary.sector} \u00b7 `}
                    {primary.geography && `${primary.geography} \u00b7 `}
                    {primary.asset_type ?? "Equity"}
                </p>
            </div>

            <div className="grid gap-4 md:grid-cols-4 mb-6">
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Market Value</p>
                    <p className="text-2xl font-semibold mt-1">
                        {formatCurrencyLocale(primary.market_value, primary.currency)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Cost Basis</p>
                    <p className="text-2xl font-semibold mt-1">
                        {formatCurrencyLocale(primary.cost_basis, primary.currency)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Unrealized P&L</p>
                    <p className={`text-2xl font-semibold mt-1 ${getPnlColor(primary.unrealized_pnl)}`}>
                        {formatCurrencyLocale(primary.unrealized_pnl, primary.currency)}
                    </p>
                    <p className={`text-sm mt-0.5 ${getPnlColor(primary.unrealized_pnl_percent)}`}>
                        {formatPnlPercent(primary.unrealized_pnl_percent)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Quantity</p>
                    <p className="text-2xl font-semibold mt-1 font-mono">{formatQuantity(primary.quantity)}</p>
                    <p className="text-xs text-muted mt-0.5">
                        {primary.cost_basis_method ?? "Default"} method
                    </p>
                </div>
            </div>

            {activeHoldings.length > 0 && (
                <div className="card mb-6">
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Active Lots</h2>
                    </div>
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
                                        <td className={`px-4 py-2 text-right font-medium ${getPnlColor(h.unrealized_pnl)}`}>
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
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Disposed Lots</h2>
                    </div>
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
                                        <td className="px-4 py-2">{h.disposal_date ? formatDateDisplay(h.disposal_date) : "\u2014"}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
