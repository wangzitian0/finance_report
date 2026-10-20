"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart2, TrendingUp, DollarSign, FileText, CalendarClock, ShieldCheck, ChevronDown } from "lucide-react";

import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatPercentFromPercentValue } from "@/lib/audit/ratio/format";
import { Badge } from "@/components/ui";
import { InfoHint, type GlossaryTerm } from "@/components/ui/InfoHint";
import { packagePeriodRequest } from "@/lib/reportPackage";
import { countLabel, readinessVariant } from "@/lib/statusLabels";
import type { AnnualizedIncomeResponse, PersonalReportPackageReadinessResponse, ReconciliationStatsResponse } from "@/lib/types";

const MORE_REPORTS = [
  { id: "cash-flow", title: "Cash Flow Statement", description: "Cash movements by operating, investing, and financing activities", icon: DollarSign, href: "/reports/cash-flow" },
  { id: "personal-package", title: "Personal Report Package", description: "Stable package contract for statements, schedules, notes, and traceability", icon: FileText, href: "/reports/package" },
];

type ReadinessLoadState = "loading" | "loaded" | "error";

function isPackageReadiness(value: unknown): value is PersonalReportPackageReadinessResponse {
  const c = value as Partial<PersonalReportPackageReadinessResponse> | null;
  return Boolean(c && typeof c.label === "string" && typeof c.action_href === "string" && typeof c.blocking_count === "number" && Array.isArray(c.blockers) && typeof c.input_coverage === "object");
}

export default function ReportsPage() {
  const [annualized, setAnnualized] = useState<AnnualizedIncomeResponse | null>(null);
  const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
  const [readiness, setReadiness] = useState<PersonalReportPackageReadinessResponse | null>(null);
  const [readinessState, setReadinessState] = useState<ReadinessLoadState>("loading");
  const [showMore, setShowMore] = useState(false);

  useEffect(() => {
    let active = true;
    const loadAnnualizedFallback = () => {
      apiOperation("get_annualized_income_income_annualized_get").then((d) => active && setAnnualized(d)).catch(() => active && setAnnualized(null));
    };
    apiOperation("reconciliation_stats_reconciliation_stats_get").then((d) => active && setStats(d)).catch(() => active && setStats(null));
    apiOperation("preview_personal_report_package_reports_package_get", {
      query: packagePeriodRequest(new Date().toISOString().slice(0, 10)),
    })
      .then((document) => {
        const inc = document?.sections?.annualized_income_long_term?.income;
        if (inc && inc.annualized_total != null && inc.currency) {
          if (active) {
            setAnnualized({
              annualized_salary: String(inc.annualized_salary ?? "0"),
              annualized_bonus: String(inc.annualized_bonus ?? "0"),
              annualized_dividend: String(inc.annualized_dividend ?? "0"),
              annualized_total: String(inc.annualized_total),
              currency: String(inc.currency),
              as_of: String(document?.context?.as_of_date ?? ""),
            });
          }
        } else {
          loadAnnualizedFallback();
        }
        if (!isPackageReadiness(document.readiness)) {
          if (active) { setReadiness(null); setReadinessState("error"); }
          return;
        }
        if (active) { setReadiness(document.readiness); setReadinessState("loaded"); }
      })
      .catch(() => {
        loadAnnualizedFallback();
        if (active) { setReadiness(null); setReadinessState("error"); }
      });
    return () => { active = false; };
  }, []);

  const matchRate = stats ? formatPercentFromPercentValue(stats.match_rate == null ? null : String(stats.match_rate), { dp: 0, fallback: "—" }) : "—";

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
          value={`${matchRate} matched`}
          caption={stats ? `${stats.unmatched_transactions} unmatched` : "Share of transactions reconciled"}
        />
      </div>

      <div className="mb-6">
        <button type="button" onClick={() => setShowMore((open) => !open)} className="btn-secondary inline-flex items-center gap-2 text-sm" aria-expanded={showMore}>
          More reports
          <ChevronDown className={`w-4 h-4 transition-transform ${showMore ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>
        {showMore && (
          <div className="grid md:grid-cols-2 gap-4 mt-4">
            {MORE_REPORTS.map((r) => <ReportNavCard key={r.id} title={r.title} description={r.description} icon={r.icon} href={r.href} />)}
          </div>
        )}
      </div>

      <div className="card flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
        <h2 className="font-semibold text-muted">Accounting Equation</h2>
        <div className="flex items-center gap-1.5 font-mono">
          <span className="text-[var(--success)]">Assets</span>
          <span className="text-muted">=</span>
          <span className="text-[var(--error)]">Liabilities</span>
          <span className="text-muted">+</span>
          <span className="text-[var(--info)]">Equity</span>
        </div>
      </div>
    </div>
  );
}

function ReportsReadinessCockpit({ readiness, loadState }: { readiness: PersonalReportPackageReadinessResponse | null; loadState: ReadinessLoadState }) {
  const coverage = readiness?.input_coverage;
  const unprovenInputCount = coverage?.unproven_input_count ?? 0;
  const blockers = readiness?.blockers ?? [];

  if (loadState === "error") {
    return (
      <section aria-label="Report readiness cockpit" className="card p-5 mb-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="font-semibold">Report readiness</h2>
            <p className="mt-2 text-sm text-muted">Readiness unavailable. Report navigation stays available, but trust status should be checked before relying on output.</p>
          </div>
          <Badge variant="warning">Readiness unavailable</Badge>
        </div>
        <Link href="/reports/package" className="btn-secondary mt-4 inline-flex text-sm">Open report package</Link>
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
            {readiness.state === "blocked" ? `${countLabel(readiness.blocking_count, "blocker")} must be resolved before reports are trusted.` : `Current package state is ${readiness.label.toLowerCase()}.`}
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
        {([
          ["Readiness", readiness.label],
          ["Blockers", countLabel(readiness.blocking_count, "blocker")],
          ["Authority decisions", countLabel(coverage?.manifest_decision_count ?? 0, "decision")],
          ["Unproven inputs", countLabel(unprovenInputCount, "unproven input")],
        ] as const).map(([dt, dd]) => (
          <div key={dt}><dt className="text-xs text-muted">{dt}</dt><dd className="mt-1 font-semibold">{dd}</dd></div>
        ))}
      </dl>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded border border-[var(--border)] p-3">
          <h3 className="text-sm font-semibold">Authority coverage</h3>
          <p className="mt-2 text-sm text-muted">
            {unprovenInputCount ? `${countLabel(unprovenInputCount, "input")} still need current authority decisions.` : "All inputs in this package document have current authority decisions."}
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <h3 className="text-sm font-semibold">Blocking actions</h3>
          {blockers.length ? (
            <ul className="mt-3 space-y-3">
              {blockers.slice(0, 2).map((b) => (
                <li key={b.code}>
                  <div className="flex items-start justify-between gap-3"><p className="text-sm font-medium">{b.label}</p><Badge variant="muted">{b.count}</Badge></div>
                  <p className="mt-1 text-xs text-muted">{b.reason}</p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-sm text-muted">No blockers reported.</p>}
        </div>
      </div>
    </section>
  );
}

function ReportNavCard({ title, description, icon: Icon, href }: { title: string; description: string; icon: React.ComponentType<{ className?: string }>; href: string }) {
  return (
    <Link href={href}>
      <div className="card p-5 transition-colors hover:border-[var(--accent)] cursor-pointer h-full">
        <div className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[var(--background-muted)] mb-3">
          <Icon className="w-5 h-5 text-[var(--accent)]" aria-hidden="true" />
        </div>
        <h3 className="font-semibold text-[var(--accent)] mb-1">{title}</h3>
        <p className="text-sm text-muted">{description}</p>
        <div className="mt-3 flex items-center text-xs text-muted"><span>View report</span></div>
      </div>
    </Link>
  );
}

function StatCard({ title, icon: Icon, href, value, caption, infoTerm }: { title: string; icon: React.ComponentType<{ className?: string }>; href?: string; value: string; caption: string; infoTerm?: GlossaryTerm }) {
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
