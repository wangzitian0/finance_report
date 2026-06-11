"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart2, TrendingUp, DollarSign, FileText, CalendarClock, ShieldCheck, ChevronDown } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import type { AnnualizedIncomeResponse, ReconciliationStatsResponse } from "@/lib/types";

// The four reports an everyday user reads (EPIC-022 AC22.3.1). Everything else
// lives behind "More" (AC22.3.2).
const MORE_REPORTS = [
    { id: "cash-flow", title: "Cash Flow Statement", description: "Cash movements by operating, investing, and financing activities", icon: DollarSign, href: "/reports/cash-flow" },
    { id: "personal-package", title: "Personal Report Package", description: "Stable package contract for statements, schedules, notes, and traceability", icon: FileText, href: "/reports/package" },
];

export default function ReportsPage() {
    const [annualized, setAnnualized] = useState<AnnualizedIncomeResponse | null>(null);
    const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
    const [showMore, setShowMore] = useState(false);

    useEffect(() => {
        let active = true;
        apiFetch<AnnualizedIncomeResponse>("/api/income/annualized")
            .then((data) => active && setAnnualized(data))
            .catch(() => active && setAnnualized(null));
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats")
            .then((data) => active && setStats(data))
            .catch(() => active && setStats(null));
        return () => {
            active = false;
        };
    }, []);

    const matchRate = stats ? Math.round((stats.match_rate ?? 0) * 100) : null;

    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Reports</h1>
                <p className="page-description">The four reports you read most. Open one to drill any amount down to its source transactions.</p>
            </div>

            <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
                <ReportNavCard title="Balance Sheet" description="Assets, liabilities, and equity at a point in time" icon={BarChart2} href="/reports/balance-sheet" />
                <ReportNavCard title="Income Statement" description="Revenue and expenses over a period" icon={TrendingUp} href="/reports/income-statement" />

                <StatCard
                    title="Annualized Income"
                    icon={CalendarClock}
                    href="/reports/package"
                    value={annualized ? formatCurrencyLocale(annualized.annualized_total, annualized.currency) : "—"}
                    caption="Projected annual total — opens the full report package"
                />
                <StatCard
                    title="Statistics Accuracy"
                    icon={ShieldCheck}
                    href="/reconciliation"
                    value={matchRate === null ? "—" : `${matchRate}% matched`}
                    caption={stats ? `${stats.unmatched_transactions} unmatched` : "Reconciliation coverage"}
                />
            </div>

            <div className="mb-6">
                <button
                    type="button"
                    onClick={() => setShowMore((open) => !open)}
                    className="btn-secondary inline-flex items-center gap-2 text-sm"
                    aria-expanded={showMore}
                >
                    More reports
                    <ChevronDown className={`w-4 h-4 transition-transform ${showMore ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>

                {showMore && (
                    <div className="grid md:grid-cols-2 gap-4 mt-4">
                        {MORE_REPORTS.map((report) => (
                            <ReportNavCard key={report.id} title={report.title} description={report.description} icon={report.icon} href={report.href} />
                        ))}
                    </div>
                )}
            </div>

            <div className="card p-5">
                <h2 className="font-semibold mb-3">Accounting Equation</h2>
                <div className="flex items-center justify-center gap-3 text-lg flex-wrap">
                    <span className="px-3 py-1.5 rounded-md bg-[var(--success-muted)] text-[var(--success)] font-mono">Assets</span>
                    <span className="text-muted">=</span>
                    <span className="px-3 py-1.5 rounded-md bg-[var(--error-muted)] text-[var(--error)] font-mono">Liabilities</span>
                    <span className="text-muted">+</span>
                    <span className="px-3 py-1.5 rounded-md bg-[var(--info-muted)] text-[var(--info)] font-mono">Equity</span>
                </div>
                <p className="text-center text-xs text-muted mt-3">All financial reports maintain this fundamental balance</p>
            </div>
        </div>
    );
}

interface ReportNavCardProps {
    title: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
    href: string;
}

function ReportNavCard({ title, description, icon: Icon, href }: ReportNavCardProps) {
    return (
        <Link href={href}>
            <div className="card p-5 transition-colors hover:border-[var(--accent)] cursor-pointer h-full">
                <div className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[var(--background-muted)] mb-3">
                    <Icon className="w-5 h-5 text-[var(--accent)]" aria-hidden="true" />
                </div>
                <h3 className="font-semibold text-[var(--accent)] mb-1">{title}</h3>
                <p className="text-sm text-muted">{description}</p>
                <div className="mt-3 flex items-center text-xs text-muted">
                    <span>View report</span>
                </div>
            </div>
        </Link>
    );
}

interface StatCardProps {
    title: string;
    icon: React.ComponentType<{ className?: string }>;
    href: string;
    value: string;
    caption: string;
}

function StatCard({ title, icon: Icon, href, value, caption }: StatCardProps) {
    return (
        <Link href={href}>
            <div className="card p-5 transition-colors hover:border-[var(--accent)] cursor-pointer h-full">
                <div className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[var(--background-muted)] mb-3">
                    <Icon className="w-5 h-5 text-[var(--accent)]" aria-hidden="true" />
                </div>
                <h3 className="font-semibold text-[var(--accent)] mb-1">{title}</h3>
                <p className="text-xl font-semibold">{value}</p>
                <p className="text-xs text-muted mt-1">{caption}</p>
            </div>
        </Link>
    );
}
