"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { CashFlowPanel, PackagePanel } from "@/components/reports/CashFlowAndPackagePanels";
import { ReportDimensionBar, StatementCockpit } from "@/components/reports/ReportShell";
import { BalanceSheetPanel, IncomeStatementPanel } from "@/components/reports/StatementPanels";
import { Badge } from "@/components/ui";
import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import { personalReportPackageQuery } from "@/hooks/usePersonalReportPackage";
import { REPORT_TABS, reportsHref, useReportFilters, type ReportFilters } from "@/hooks/useReportFilters";
import { countLabel, readinessVariant } from "@/lib/statusLabels";
import type { PersonalReportPackageReadinessResponse } from "@/lib/types";

/**
 * `/reports`: the three statements and the report package as tabs of one page (#2621 LC).
 *
 * `?tab=` selects the tab and Overview is the default. The old routes `/reports/balance-sheet`,
 * `/reports/income-statement`, `/reports/cash-flow` and `/reports/package` redirect here with
 * their tab. One dimension bar sets the period and the currency of every tab.
 */
export default function ReportsPage() {
  const filters = useReportFilters();
  const { tab } = filters;

  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">Reports</h1>
        <p className="page-description">Your three statements and the report package for one period. Select an amount to see its source transactions.</p>
      </div>
      <div className="mb-4">
        <ReportDimensionBar filters={filters} showScope={tab === "overview" || tab === "balance-sheet"} />
      </div>
      <nav role="tablist" aria-label="Report tabs" className="mb-6 flex gap-1 overflow-x-auto whitespace-nowrap border-b border-[var(--border)]">
        {REPORT_TABS.map((item) => (
          <Link
            key={item.id}
            href={reportsHref(item.id, filters.dimensionQuery)}
            role="tab"
            aria-selected={tab === item.id}
            className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === item.id
                ? "border-[var(--accent)] text-[var(--foreground)]"
                : "border-transparent text-muted hover:text-[var(--foreground)]"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div role="tabpanel" aria-label={REPORT_TABS.find((item) => item.id === tab)?.label}>
        {tab === "overview" && <ReportsOverview filters={filters} />}
        {tab === "balance-sheet" && <BalanceSheetPanel filters={filters} />}
        {tab === "income-statement" && <IncomeStatementPanel filters={filters} />}
        {tab === "cash-flow" && <CashFlowPanel filters={filters} />}
        {tab === "package" && <PackagePanel filters={filters} />}
      </div>
    </div>
  );
}

type ReadinessLoadState = "loading" | "loaded" | "error";

/** A readiness action that opens the report package. It opens the Package tab with the bar period. */
const REPORT_PACKAGE_HREF = /^\/reports(\/package)?([?#].*)?$/;

function isPackageReadiness(value: unknown): value is PersonalReportPackageReadinessResponse {
  const c = value as Partial<PersonalReportPackageReadinessResponse> | null;
  return Boolean(c && typeof c.label === "string" && typeof c.action_href === "string" && typeof c.blocking_count === "number" && Array.isArray(c.blockers) && typeof c.input_coverage === "object");
}

/** The Overview tab: trust first. The readiness of the report package, then the three statement cards. */
function ReportsOverview({ filters }: { filters: ReportFilters }) {
  // The Package tab reads the same preview key (#2583 S4): a switch to the Package tab issues no request.
  const packageQuery = useQuery({
    ...personalReportPackageQuery({ frameworkId: null, reportDate: filters.endDate, startDate: filters.startDate, currency: filters.currency }),
    // The period waits for the coverage start (#2646).
    enabled: filters.ready,
  });
  const readiness = isPackageReadiness(packageQuery.data?.readiness) ? packageQuery.data.readiness : null;
  const loadState: ReadinessLoadState = packageQuery.isError
    ? "error"
    : packageQuery.isSuccess
      ? (readiness ? "loaded" : "error")
      : "loading";

  return (
    <div className="space-y-6">
      <ReportsReadinessCockpit readiness={readiness} loadState={loadState} packageHref={reportsHref("package", filters.dimensionQuery)} />
      <StatementCockpit filters={filters} />
    </div>
  );
}

function ReportsReadinessCockpit({
  readiness,
  loadState,
  packageHref,
}: {
  readiness: PersonalReportPackageReadinessResponse | null;
  loadState: ReadinessLoadState;
  packageHref: string;
}) {
  const coverage = readiness?.input_coverage;
  const unprovenInputCount = coverage?.unproven_input_count ?? 0;
  const blockers = readiness?.blockers ?? [];

  if (loadState === "error") {
    return (
      <section aria-label="Report readiness cockpit" className="card p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="font-semibold">Report readiness</h2>
            <p className="mt-2 text-sm text-muted">Readiness unavailable. The report tabs stay available, but check trust status before you rely on output.</p>
          </div>
          <Badge variant="warning">Readiness unavailable</Badge>
        </div>
        <Link href={packageHref} className="btn-secondary mt-4 inline-flex text-sm">Open report package</Link>
      </section>
    );
  }

  if (loadState === "loading" || !readiness) {
    return (
      <section aria-label="Report readiness cockpit" className="card p-5" aria-busy="true">
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
    <section aria-label="Report readiness cockpit" className="card p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Report readiness</h2>
          <p className="mt-2 text-sm text-muted">
            {readiness.state === "blocked" ? `${countLabel(readiness.blocking_count, "blocker")} must be resolved before reports are trusted.` : `Current package state is ${readiness.label.toLowerCase()}.`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={readinessVariant(readiness.state)}>{readiness.label}</Badge>
          <Link href={REPORT_PACKAGE_HREF.test(readiness.action_href) ? packageHref : readiness.action_href} className="btn-secondary text-sm">
            {readiness.blocking_count > 0 ? "Resolve report blockers" : "Open readiness path"}
          </Link>
        </div>
      </div>

      <dl className="mt-5 grid gap-3 text-sm md:grid-cols-4">
        {([
          ["Readiness", readiness.label],
          ["Blockers", countLabel(readiness.blocking_count, "blocker")],
          ["Confirmed items", countLabel(coverage?.manifest_decision_count ?? 0, "decision")],
          ["Unconfirmed items", countLabel(unprovenInputCount, "unconfirmed item")],
        ] as const).map(([dt, dd]) => (
          <div key={dt}><dt className="text-xs text-muted">{dt}</dt><dd className="mt-1 font-semibold">{dd}</dd></div>
        ))}
      </dl>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded border border-[var(--border)] p-3">
          <h3 className="text-sm font-semibold">Verified sources</h3>
          <p className="mt-2 text-sm text-muted">
            {unprovenInputCount ? `${countLabel(unprovenInputCount, "input")} still need confirmation.` : "All inputs in this report package are confirmed."}
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <h3 className="text-sm font-semibold">Blocking actions</h3>
          {blockers.length ? (
            <ul className="mt-3 space-y-3">
              {blockers.slice(0, 2).map((b) => (
                <li key={b.code}>
                  <div className="flex items-start justify-between gap-3"><p className="text-sm font-medium">{humanizeWorkflowText(b.label)}</p><Badge variant="muted">{b.count}</Badge></div>
                  <p className="mt-1 text-xs text-muted">{humanizeWorkflowText(b.reason)}</p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-sm text-muted">No blockers reported.</p>}
        </div>
      </div>
    </section>
  );
}
