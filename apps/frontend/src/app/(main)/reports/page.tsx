"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart2, TrendingUp, DollarSign, FileText, CalendarClock, ShieldCheck, ChevronDown } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/money";
import { Badge, type BadgeVariant } from "@/components/ui";
import { InfoHint, type GlossaryTerm } from "@/components/ui/InfoHint";
import { reportPeriodStart } from "@/hooks/usePersonalReportPackage";
import type { AnnualizedIncomeResponse, PersonalReportPackageReadinessResponse, ReconciliationStatsResponse } from "@/lib/types";

// The four reports an everyday user reads (EPIC-022 AC22.3.1). Everything else
// lives behind "More" (AC22.3.2).
const MORE_REPORTS = [
    { id: "cash-flow", title: "Cash Flow Statement", description: "Cash movements by operating, investing, and financing activities", icon: DollarSign, href: "/reports/cash-flow" },
    { id: "personal-package", title: "Personal Report Package", description: "Stable package contract for statements, schedules, notes, and traceability", icon: FileText, href: "/reports/package" },
];

type ReadinessLoadState = "loading" | "ready" | "error";

const SOURCE_CLASS_LABELS: Record<string, string> = {
    bank_statement: "Bank statements",
    brokerage_statement: "Brokerage statements",
    settlement_note: "Settlement notes",
    esop_rsu_plan: "ESOP / RSU plans",
    property_statement: "Property statements",
    liability_statement: "Liability statements",
    csv_export: "CSV exports",
    manual_record: "Manual records",
};

function packageReadinessQuery(): string {
    const reportDate = new Date().toISOString().slice(0, 10);
    const params = new URLSearchParams({
        start_date: reportPeriodStart(reportDate),
        end_date: reportDate,
        as_of_date: reportDate,
    });
    return `?${params.toString()}`;
}

function countLabel(count: number, singular: string, plural = `${singular}s`) {
    return `${count} ${count === 1 ? singular : plural}`;
}

function sourceClassLabel(sourceClass: string): string {
    return SOURCE_CLASS_LABELS[sourceClass] ?? sourceClass.replaceAll("_", " ");
}

function readinessVariant(state?: PersonalReportPackageReadinessResponse["state"]): BadgeVariant {
    switch (state) {
        case "ready":
        case "generated":
            return "success";
        case "blocked":
            return "error";
        case "processing":
            return "info";
        case "stale":
            return "warning";
        case "draft":
        default:
            return "muted";
    }
}

function isPackageReadiness(value: unknown): value is PersonalReportPackageReadinessResponse {
    const candidate = value as Partial<PersonalReportPackageReadinessResponse> | null;
    return Boolean(
        candidate &&
        typeof candidate.label === "string" &&
        typeof candidate.action_href === "string" &&
        typeof candidate.blocking_count === "number" &&
        Array.isArray(candidate.blockers),
    );
}

export default function ReportsPage() {
    const [annualized, setAnnualized] = useState<AnnualizedIncomeResponse | null>(null);
    const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
    const [readiness, setReadiness] = useState<PersonalReportPackageReadinessResponse | null>(null);
    const [readinessState, setReadinessState] = useState<ReadinessLoadState>("loading");
    const [showMore, setShowMore] = useState(false);

    useEffect(() => {
        let active = true;
        apiFetch<AnnualizedIncomeResponse>("/api/income/annualized")
            .then((data) => active && setAnnualized(data))
            .catch(() => active && setAnnualized(null));
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats")
            .then((data) => active && setStats(data))
            .catch(() => active && setStats(null));
        apiFetch<PersonalReportPackageReadinessResponse>(`/api/reports/package/readiness${packageReadinessQuery()}`)
            .then((data) => {
                if (!isPackageReadiness(data)) {
                    if (active) {
                        setReadiness(null);
                        setReadinessState("error");
                    }
                    return;
                }
                if (active) {
                    setReadiness(data);
                    setReadinessState("ready");
                }
            })
            .catch(() => {
                if (active) {
                    setReadiness(null);
                    setReadinessState("error");
                }
            });
        return () => {
            active = false;
        };
    }, []);

    // `match_rate` is already a 0–100 percentage from the backend
    // (matched / total * 100), so it must not be multiplied by 100 again.
    const matchRate = stats ? Math.round(stats.match_rate ?? 0) : null;

    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Reports</h1>
                <p className="page-description">The four reports you read most. Open one to drill any amount down to its source transactions.</p>
            </div>

            <ReportsReadinessCockpit readiness={readiness} loadState={readinessState} />

            <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
                <ReportNavCard title="Balance Sheet" description="Assets, liabilities, and equity at a point in time" icon={BarChart2} href="/reports/balance-sheet" />
                <ReportNavCard title="Income Statement" description="Revenue and expenses over a period" icon={TrendingUp} href="/reports/income-statement" />

                <StatCard
                    title="Annualized Income"
                    icon={CalendarClock}
                    href="/reports/package"
                    value={annualized ? formatCurrencyLocale(annualized.annualized_total, annualized.currency) : "—"}
                    caption="Projected annual total — see the full breakdown in the report package →"
                />
                <StatCard
                    title="Reconciliation coverage"
                    icon={ShieldCheck}
                    infoTerm="reconciliation_coverage"
                    value={matchRate === null ? "—" : `${matchRate}% matched`}
                    caption={stats ? `${stats.unmatched_transactions} unmatched` : "Share of transactions reconciled"}
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

function ReportsReadinessCockpit({
    readiness,
    loadState,
}: {
    readiness: PersonalReportPackageReadinessResponse | null;
    loadState: ReadinessLoadState;
}) {
    const sourceTrust = readiness?.source_trust_summary;
    const gapClasses = sourceTrust?.gap_source_classes ?? [];
    const sourceClassCount = sourceTrust?.source_classes.length ?? 0;
    const blockers = readiness?.blockers ?? [];

    if (loadState === "error") {
        return (
            <section aria-label="Report readiness cockpit" className="card p-5 mb-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                        <h2 className="font-semibold">Report readiness</h2>
                        <p className="mt-2 text-sm text-muted">
                            Readiness unavailable. Report navigation stays available, but trust status should be checked before relying on output.
                        </p>
                    </div>
                    <Badge variant="warning">Readiness unavailable</Badge>
                </div>
                <Link href="/reports/package" className="btn-secondary mt-4 inline-flex text-sm">
                    Open report package
                </Link>
            </section>
        );
    }

    if (loadState === "loading" || !readiness) {
        return (
            <section aria-label="Report readiness cockpit" className="card p-5 mb-6" aria-busy="true">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                        <h2 className="font-semibold">Report readiness</h2>
                        <p className="mt-2 text-sm text-muted">Checking report readiness before showing trust status.</p>
                    </div>
                    <Badge variant="muted">Checking</Badge>
                </div>
            </section>
        );
    }

    return (
        <section aria-label="Report readiness cockpit" className="card p-5 mb-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                    <h2 className="font-semibold">Report readiness</h2>
                    <p className="mt-2 text-sm text-muted">
                        {readiness.state === "blocked"
                            ? `${countLabel(readiness.blocking_count, "blocker")} must be resolved before reports are trusted.`
                            : `Current package state is ${readiness.label.toLowerCase()}.`}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={readinessVariant(readiness.state)}>{readiness.label}</Badge>
                    <Link href={readiness.action_href} className="btn-secondary text-sm">
                        {readiness.blocking_count > 0 ? "Resolve report blockers" : "Open readiness path"}
                    </Link>
                </div>
            </div>

            <dl className="mt-5 grid gap-3 text-sm md:grid-cols-4">
                <div>
                    <dt className="text-xs text-muted">Readiness</dt>
                    <dd className="mt-1 font-semibold">{readiness.label}</dd>
                </div>
                <div>
                    <dt className="text-xs text-muted">Blockers</dt>
                    <dd className="mt-1 font-semibold">{countLabel(readiness.blocking_count, "blocker")}</dd>
                </div>
                <div>
                    <dt className="text-xs text-muted">Source classes</dt>
                    <dd className="mt-1 font-semibold">{countLabel(sourceClassCount, "class", "classes")}</dd>
                </div>
                <div>
                    <dt className="text-xs text-muted">Trust gaps</dt>
                    <dd className="mt-1 font-semibold">{countLabel(gapClasses.length, "trust gap")}</dd>
                </div>
            </dl>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
                <div className="rounded border border-[var(--border)] p-3">
                    <h3 className="text-sm font-semibold">Source gaps</h3>
                    {gapClasses.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                            {gapClasses.map((sourceClass) => (
                                <Badge key={sourceClass} variant="warning">
                                    {sourceClassLabel(sourceClass)}
                                </Badge>
                            ))}
                        </div>
                    ) : (
                        <p className="mt-2 text-sm text-muted">No source gaps reported.</p>
                    )}
                </div>
                <div className="rounded border border-[var(--border)] p-3">
                    <h3 className="text-sm font-semibold">Blocking actions</h3>
                    {blockers.length ? (
                        <ul className="mt-3 space-y-3">
                            {blockers.slice(0, 2).map((blocker) => (
                                <li key={blocker.code}>
                                    <div className="flex items-start justify-between gap-3">
                                        <p className="text-sm font-medium">{blocker.label}</p>
                                        <Badge variant="muted">{blocker.count}</Badge>
                                    </div>
                                    <p className="mt-1 text-xs text-muted">{blocker.reason}</p>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="mt-2 text-sm text-muted">No blockers reported.</p>
                    )}
                </div>
            </div>
        </section>
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
    /** Optional destination. Omit for a display-only stat that must not pull an
        everyday user into an Advanced surface (EPIC-022 AC22.9.1). */
    href?: string;
    value: string;
    caption: string;
    /** Optional glossary term rendered as an InfoHint next to the title. */
    infoTerm?: GlossaryTerm;
}

function StatCard({ title, icon: Icon, href, value, caption, infoTerm }: StatCardProps) {
    const body = (
        <div className={`card p-5 transition-colors h-full ${href ? "hover:border-[var(--accent)] cursor-pointer" : ""}`}>
            <div className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[var(--background-muted)] mb-3">
                <Icon className="w-5 h-5 text-[var(--accent)]" aria-hidden="true" />
            </div>
            <div className="mb-1 flex items-center">
                <h3 className="font-semibold text-[var(--accent)]">{title}</h3>
                {infoTerm && <InfoHint term={infoTerm} label={title} />}
            </div>
            <p className="text-xl font-semibold">{value}</p>
            <p className="text-xs text-muted mt-1">{caption}</p>
        </div>
    );
    return href ? <Link href={href}>{body}</Link> : body;
}
