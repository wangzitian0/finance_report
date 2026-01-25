"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { ManagedPosition, ManagedPositionListResponse, ReconcilePositionsResponse } from "@/lib/types";

const STATUS_FILTERS = ["All", "active", "disposed"] as const;

function formatQuantity(quantity: string): string {
    const num = parseFloat(quantity);
    if (Number.isInteger(num)) return num.toLocaleString();
    return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

function formatCurrency(amount: string, currency: string): string {
    const num = parseFloat(amount);
    return `${currency} ${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function AssetsPage() {
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [activeFilter, setActiveFilter] = useState<string>("All");

    const statusParam = activeFilter === "All" ? "" : `?status_filter=${activeFilter}`;

    const { data, isLoading, error, refetch } = useQuery({
        queryKey: ["positions", activeFilter],
        queryFn: () => apiFetch<ManagedPositionListResponse>(`/api/assets/positions${statusParam}`),
    });

    const reconcileMutation = useMutation({
        mutationFn: () => apiFetch<ReconcilePositionsResponse>("/api/assets/reconcile", { method: "POST" }),
        onSuccess: (result) => {
            const total = result.created + result.updated + result.disposed;
            if (result.skipped > 0) {
                const skippedList = result.skipped_assets.slice(0, 3).join(", ");
                const suffix = result.skipped_assets.length > 3 ? ` and ${result.skipped_assets.length - 3} more` : "";
                showToast(
                    `Reconciled ${total} positions. ⚠️ ${result.skipped} skipped due to incomplete data: ${skippedList}${suffix}`,
                    "warning"
                );
            } else {
                showToast(
                    `Reconciled ${total} positions (${result.created} created, ${result.updated} updated, ${result.disposed} disposed)`,
                    "success"
                );
            }
            queryClient.invalidateQueries({ queryKey: ["positions"] });
        },
        onError: (err: Error) => {
            showToast(`Failed to reconcile: ${err.message}`, "error");
        },
    });

    const positions = data?.items ?? [];

    const groupedByBroker = positions.reduce((groups, pos) => {
        const broker = pos.account_name ?? "Unknown";
        if (!groups[broker]) groups[broker] = [];
        groups[broker].push(pos);
        return groups;
    }, {} as Record<string, ManagedPosition[]>);

    const totalsByCurrency = positions.reduce((totals, pos) => {
        const currency = pos.currency || "USD";
        totals[currency] = (totals[currency] || 0) + parseFloat(pos.cost_basis);
        return totals;
    }, {} as Record<string, number>);

    return (
        <div className="p-6">
            <div className="page-header flex items-center justify-between">
                <div>
                    <h1 className="page-title">Assets</h1>
                    <p className="page-description">Your investment holdings across brokers</p>
                </div>
                <button
                    onClick={() => reconcileMutation.mutate()}
                    disabled={reconcileMutation.isPending}
                    className="btn-primary flex items-center gap-2"
                >
                    {reconcileMutation.isPending ? (
                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    )}
                    Reconcile Positions
                </button>
            </div>

            <div className="flex items-center justify-between mb-6">
                <div className="flex gap-1 bg-[var(--background-muted)] p-1 rounded-lg w-fit">
                    {STATUS_FILTERS.map((status) => (
                        <button
                            key={status}
                            onClick={() => setActiveFilter(status)}
                            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${
                                activeFilter === status
                                    ? "bg-[var(--background-card)] text-[var(--foreground)]"
                                    : "text-muted hover:text-[var(--foreground)]"
                            }`}
                        >
                            {status}
                        </button>
                    ))}
                </div>

                {!isLoading && !error && positions.length > 0 && (
                    <div className="text-sm text-muted">
                        Total Value: <span className="font-semibold text-[var(--foreground)]">
                            {Object.entries(totalsByCurrency).map(([currency, total], i) => (
                                <span key={currency}>
                                    {i > 0 && " + "}
                                    {formatCurrency(total.toString(), currency)}
                                </span>
                            ))}
                        </span>
                    </div>
                )}
            </div>

            {error && (
                <div className="mb-4 alert-error">
                    {error instanceof Error ? error.message : "Failed to load positions"}
                </div>
            )}

            {isLoading ? (
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading positions...</p>
                </div>
            ) : error ? (
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-soft)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load positions</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <button onClick={() => refetch()} className="btn-secondary" aria-label="Retry loading positions">
                        Retry
                    </button>
                </div>
            ) : positions.length === 0 ? (
                <div className="card p-8 text-center">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--background-muted)] text-muted mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                        </svg>
                    </div>
                    <p className="text-muted mb-4">No positions found</p>
                    <p className="text-sm text-muted mb-6">
                        Upload brokerage statements and run reconciliation to see your holdings here.
                    </p>
                    <button onClick={() => reconcileMutation.mutate()} className="btn-primary" disabled={reconcileMutation.isPending}>
                        Run Reconciliation
                    </button>
                </div>
            ) : (
                <div className="space-y-4">
                    {Object.entries(groupedByBroker).map(([broker, brokerPositions]) => {
                        const brokerTotalsByCurrency = brokerPositions.reduce((totals, p) => {
                            const currency = p.currency || "USD";
                            totals[currency] = (totals[currency] || 0) + parseFloat(p.cost_basis);
                            return totals;
                        }, {} as Record<string, number>);
                        return (
                            <div key={broker} className="card">
                                <div className="card-header flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="badge badge-primary">{broker}</span>
                                        <span className="text-xs text-muted">{brokerPositions.length} positions</span>
                                    </div>
                                    <span className="text-sm font-medium">
                                        {Object.entries(brokerTotalsByCurrency).map(([currency, total], i) => (
                                            <span key={currency}>
                                                {i > 0 && " + "}
                                                {formatCurrency(total.toString(), currency)}
                                            </span>
                                        ))}
                                    </span>
                                </div>
                                <div className="divide-y divide-[var(--border)]">
                                    {brokerPositions.map((position) => (
                                        <div key={position.id} className="px-6 py-3 flex items-center justify-between hover:bg-[var(--background-muted)]/50 transition-colors">
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium font-mono">{position.asset_identifier}</span>
                                                    <span className={`badge ${position.status === "active" ? "badge-success" : "badge-muted"}`}>
                                                        {position.status}
                                                    </span>
                                                </div>
                                                <div className="text-xs text-muted mt-0.5">
                                                    Acquired: {new Date(position.acquisition_date).toLocaleDateString()}
                                                    {position.disposal_date && ` | Disposed: ${new Date(position.disposal_date).toLocaleDateString()}`}
                                                </div>
                                            </div>
                                            <div className="text-right">
                                                <div className="font-semibold">{formatQuantity(position.quantity)} units</div>
                                                <div className="text-sm text-muted">{formatCurrency(position.cost_basis, position.currency)}</div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
