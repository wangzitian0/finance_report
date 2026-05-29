"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { compareAmounts, formatAmount } from "@/lib/currency";
import { PerformanceMetrics } from "@/lib/types";

function safeComparePercent(value: string): number | null {
    try {
        return compareAmounts(value, "0");
    } catch {
        return null;
    }
}

function formatPercent(value: string): string {
    const comparison = safeComparePercent(value);
    if (comparison === null) return "—";
    const sign = comparison > 0 ? "+" : "";
    return `${sign}${formatAmount(value, 2)}%`;
}

function getPercentColor(value: string): string {
    const comparison = safeComparePercent(value);
    if (comparison === null || comparison === 0) return "";
    return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

export function PerformanceCard() {
    const { data, isLoading, error } = useQuery({
        queryKey: ["portfolio-performance"],
        queryFn: () => apiFetch<PerformanceMetrics>("/api/portfolio/performance"),
    });

    if (isLoading) {
        return (
            <div className="card p-5">
                <p className="text-xs text-muted uppercase tracking-wide mb-3">Performance</p>
                <div className="flex items-center justify-center py-4">
                    <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin text-muted" />
                </div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="card p-5">
                <p className="text-xs text-muted uppercase tracking-wide mb-3">Performance</p>
                <p className="text-sm text-muted">Unable to load performance metrics</p>
            </div>
        );
    }

    const metrics = [
        { label: "XIRR", value: data.xirr, tooltip: "Extended Internal Rate of Return — annualized return accounting for irregular cash flows" },
        { label: "TWR", value: data.time_weighted_return, tooltip: "Time-Weighted Return — measures portfolio manager performance" },
        { label: "MWR", value: data.money_weighted_return, tooltip: "Money-Weighted Return — measures investor experience including timing" },
    ];

    return (
        <div className="card p-5">
            <p className="text-xs text-muted uppercase tracking-wide mb-3">Performance Metrics</p>
            <div className="grid grid-cols-3 gap-4">
                {metrics.map((m) => (
                    <div key={m.label} title={m.tooltip}>
                        <p className="text-xs text-muted">{m.label}</p>
                        <p className={`text-xl font-semibold mt-0.5 ${getPercentColor(m.value)}`}>
                            {formatPercent(m.value)}
                        </p>
                    </div>
                ))}
            </div>
        </div>
    );
}
