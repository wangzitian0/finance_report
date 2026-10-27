"use client";

import { useState } from "react";
import { infiniteQueryOptions, keepPreviousData, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { SankeyChart } from "@/components/charts/SankeyChart";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ExportCsvButton, FxWarningBanner, ReportPageShell, ReportToolbar } from "@/components/reports/ReportShell";
import {
  FRAMEWORK_LABELS,
  LineagePanelModal,
  PackageAnnualizedScheduleSection,
  PackageCover,
  PackageExportContractSection,
  PackageFrameworkPolicySection,
  PackageFrameworkSelection,
  PackageInputManifestSection,
  PackageLoadingSkeleton,
  PackageNotesSection,
  PackageReadinessSection,
  PackageSectionCards,
  PackageSetupGuidance,
  PackageSnapshotsCard,
  PackageTableOfContents,
  PackageTraceabilitySection,
  evidenceBundleReferences,
  packageTocLinks,
  type LineagePanelState,
} from "@/components/reports/package/shared";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";
import { apiOperation, apiOperationDownload } from "@/lib/api-client";
import { compareAmounts, formatCurrencyLocale, toDecimal } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { lineageQuery } from "@/lib/lineage";
import { loadLineageAnchorForLine } from "@/lib/packageEvidence";
import { useApiQuery } from "@/hooks/useApiQuery";
import {
  generatePackageSnapshot,
  invalidateReportPackageQueries,
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import type { ReportFilters } from "@/hooks/useReportFilters";
import { cashFlowQueryKey, SHARED_STALE_MS } from "@/lib/sharedQueries";
import { countLabel } from "@/lib/statusLabels";
import {
  normalizeFxWarningRows,
  type CashFlowLine,
  type CashFlowLineEventsPage,
  type PersonalReportPackageDocument,
  type PersonalReportPackageSnapshotSummary,
  type PersonalReportPackageTraceabilityLineSummary,
  type PersonalReportingFrameworkId,
} from "@/lib/types";

// The cash-flow statement carries an event count for each line (#2583 S10). The events of a
// line load page by page when the user opens the line. This component mounts only for an open
// line, so a closed line never issues a request. Each page request runs the cash-flow builder
// again, so a page holds 200 events and the open and reopened line share one cache entry.

/** Page size of the line events. The backend maximum is 500. */
const CASH_FLOW_LINE_EVENTS_PAGE_SIZE = 200;

interface CashFlowPeriod {
  start_date: string;
  end_date: string;
  currency: string;
}

/** The accessible name of a line: its description holds the direction and the counterparts. */
function cashFlowLineLabel(line: CashFlowLine): string {
  return line.description || line.subcategory;
}

function nextOffset(page: CashFlowLineEventsPage): number | undefined {
  const next = page.offset + page.limit;
  return next < page.total ? next : undefined;
}

/** The one cache entry of the events of a line. The "report" key prefix is ledger-derived. */
function cashFlowLineEventsQueryOptions(period: CashFlowPeriod, lineId: string) {
  return infiniteQueryOptions({
    queryKey: ["report", "cash-flow", "line-events", period.start_date, period.end_date, period.currency, lineId] as const,
    queryFn: ({ pageParam, signal }) =>
      apiOperation("list_cash_flow_line_events_reports_cash_flow_line_events_get", {
        query: { ...period, line_id: lineId, limit: CASH_FLOW_LINE_EVENTS_PAGE_SIZE, offset: pageParam },
        signal,
      }),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    staleTime: SHARED_STALE_MS,
  });
}

/** The events of one open cash-flow line, with the amounts in the report currency. */
function CashFlowLineEvents({ period, line }: { period: CashFlowPeriod; line: CashFlowLine }) {
  const query = useInfiniteQuery(cashFlowLineEventsQueryOptions(period, line.line_id));
  const events = query.data?.pages.flatMap((page) => page.events ?? []) ?? [];
  const total = query.data?.pages[0]?.total ?? line.event_count;

  return (
    <section
      id={`cash-flow-events-${line.line_id}`}
      aria-label={`Events for ${cashFlowLineLabel(line)}`}
      className="mt-2 rounded-md border border-[var(--border)] p-2"
    >
      <p className="text-xs font-medium">{`${events.length} of ${countLabel(total, "event")}`}</p>
      {query.isLoading ? (
        <p role="status" className="mt-1 text-xs text-muted">
          Loading events...
        </p>
      ) : null}
      {events.length > 0 ? (
        <ul className="mt-1 max-h-64 space-y-1 overflow-y-auto pr-1">
          {events.map((event) => (
            <li key={`${event.journal_entry_id}-${event.reason_code ?? ""}`} className="flex justify-between gap-2 text-xs">
              <span className="min-w-0">
                <span className="text-muted">{formatDateDisplay(event.entry_date)}</span>{" "}
                <span className="break-words">{event.memo}</span>
              </span>
              <span className="shrink-0 font-medium">{formatCurrencyLocale(event.amount, period.currency)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {query.error ? (
        <p className="mt-1 text-xs text-[var(--error)]">
          {query.error instanceof Error ? query.error.message : "Failed to load the events."}
        </p>
      ) : null}
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary mt-2 text-xs"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : "Load more events"}
        </button>
      ) : null}
    </section>
  );
}

/** The Cash flow tab of `/reports`: cash movements of the dimension-bar period. */
export function CashFlowPanel({ filters }: { filters: ReportFilters }) {
  const { startDate, endDate, currency } = filters;
  const [drillTarget, setDrillTarget] = useState<AccountLineageTarget | null>(null);
  // Open lines, keyed by the report period and the line id: a new period starts with every line closed.
  const [openLines, setOpenLines] = useState<ReadonlySet<string>>(new Set());

  const reportQuery = useApiQuery(
    cashFlowQueryKey({ startDate, endDate, currency }),
    "cash_flow_reports_cash_flow_get",
    { query: { start_date: startDate, end_date: endDate, currency } },
    {
      // The period waits for the coverage start (#2646).
      enabled: filters.ready,
      placeholderData: keepPreviousData,
      select: (data) => ({ ...data, fx_warnings: normalizeFxWarningRows(data.fx_warnings) }),
    },
  );
  const report = reportQuery.data ?? null;
  const period: CashFlowPeriod | null = report
    ? { start_date: report.start_date, end_date: report.end_date, currency: report.currency }
    : null;
  const openKey = (line: CashFlowLine) => (period ? `${period.start_date}|${period.end_date}|${period.currency}|${line.line_id}` : "");
  const toggleLine = (key: string) =>
    setOpenLines((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const incompleteOpeningCoverage = report?.proof_reasons?.includes("opening_coverage_starts_after_period") ?? false;
  const unverified = report?.proof_state === "unproven";
  const summary = report?.summary;
  const aiPrompt = `Analyze my cash flow from ${startDate} to ${endDate} in ${report?.currency ?? currency ?? "my base currency"}. What are the main sources and uses of cash?`;

  const renderSection = (title: string, lines: CashFlowLine[], colorClass: string) => (
    <div className="card p-5">
      <h3 className={`font-semibold mb-4 ${colorClass}`}>{title}</h3>
      {lines.length > 0 ? (
        <div className="space-y-2">
          {lines.map((line, idx) => {
            const key = openKey(line);
            const open = period !== null && openLines.has(key);
            const label = cashFlowLineLabel(line);
            return (
              <div key={line.line_id ?? `${line.subcategory}-${idx}`} className="p-2 rounded-md bg-[var(--background-muted)] text-sm">
                <div className="flex justify-between items-center">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{line.subcategory}</p>
                    {line.description && <p className="text-xs text-muted truncate">{line.description}</p>}
                  </div>
                  {line.account_id ? (
                    <button
                      type="button"
                      onClick={() =>
                        setDrillTarget({
                          accountId: line.account_id!,
                          accountName: line.subcategory,
                          asOfDate: endDate,
                          startDate,
                          currency: report!.currency,
                        })
                      }
                      className="font-medium ml-2 underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                      aria-label={`View source transactions for ${line.subcategory}`}
                    >
                      {report ? formatCurrencyLocale(line.amount, report.currency) : "—"}
                    </button>
                  ) : (
                    <span className="font-medium ml-2">{report ? formatCurrencyLocale(line.amount, report.currency) : "—"}</span>
                  )}
                </div>
                {period && line.event_count > 0 ? (
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={`cash-flow-events-${line.line_id}`}
                    aria-label={`${countLabel(line.event_count, "event")} for ${label}`}
                    onClick={() => toggleLine(key)}
                    className="mt-1 text-xs text-muted underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
                  >
                    {countLabel(line.event_count, "event")}
                  </button>
                ) : null}
                {open && period ? <CashFlowLineEvents period={period} line={line} /> : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted">No items in this category.</p>
      )}
    </div>
  );

  return (
    <ReportPageShell
      title="Cash Flow Statement"
      description="Operating, Investing, and Financing activities"
      loadingLabel="Loading cash flow"
      isLoading={!filters.ready || reportQuery.isLoading}
      isError={reportQuery.isError}
      errorMessage={reportQuery.error?.message}
      onRetry={() => void reportQuery.refetch()}
      toolbar={
        <ReportToolbar
          aiPrompt={aiPrompt}
          exportControl={<ExportCsvButton request={{ query: { report_type: "cash-flow", format: "csv", start_date: startDate, end_date: endDate, currency } }} />}
        />
      }
    >
      <FxWarningBanner warnings={report?.fx_warnings} />

      {summary && (
        <div className="grid gap-4 md:grid-cols-3 mb-6">
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Net Cash Flow</p>
            <p className={`text-2xl font-semibold mt-1 ${compareAmounts(summary.net_cash_flow, "0") >= 0 ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
              {formatCurrencyLocale(summary.net_cash_flow, report?.currency || "SGD")}
            </p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">{incompleteOpeningCoverage ? "Known Beginning Cash" : "Beginning Cash"}</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.beginning_cash, report?.currency || "SGD")}</p>
          </div>
          <div className="card p-5">
            <p className="text-xs text-muted uppercase">Ending Cash</p>
            <p className="text-2xl font-semibold mt-1">{formatCurrencyLocale(summary.ending_cash, report?.currency || "SGD")}</p>
          </div>
        </div>
      )}

      {summary && (() => {
        const cur = report?.currency || "SGD";
        const beginning = toDecimal(summary.beginning_cash);
        const net = toDecimal(summary.net_cash_flow);
        const ending = toDecimal(summary.ending_cash);
        const openingStock = toDecimal(report?.cash_bridge?.opening_stock_adjustment ?? "0");
        const unclassifiedCash = toDecimal(report?.cash_bridge?.unclassified_cash ?? "0");
        const expectedEnding = beginning.plus(net).plus(openingStock);
        const drift = expectedEnding.minus(ending);
        const reconciles = drift.abs().lessThanOrEqualTo("0.01");
        return (
          <div className="card p-5 mb-6" aria-label="Cash reconciliation">
            <p className="text-xs text-muted uppercase mb-3">Cash reconciliation</p>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span>{incompleteOpeningCoverage ? "Known beginning cash" : "Beginning cash"} <strong>{formatCurrencyLocale(beginning, cur)}</strong></span>
              <span className="text-muted">+</span>
              <span>Net cash flow <strong className={net.isNegative() ? "text-[var(--error)]" : "text-[var(--success)]"}>{formatCurrencyLocale(net, cur)}</strong></span>
              {!openingStock.isZero() && (
                <>
                  <span className="text-muted">+</span>
                  <span>Opening balance adjustment <strong>{formatCurrencyLocale(openingStock, cur)}</strong></span>
                </>
              )}
              <span className="text-muted">=</span>
              <span>Ending cash <strong>{formatCurrencyLocale(ending, cur)}</strong></span>
              <span className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${reconciles && !unverified ? "bg-[var(--success-muted)] text-[var(--success)]" : "bg-[var(--warning-muted)] text-[var(--warning)]"}`}>
                {!reconciles ? "⚠ Does not tie" : incompleteOpeningCoverage ? "⚠ Coverage incomplete" : unverified ? "⚠ Not yet verified" : "✓ Reconciles"}
              </span>
            </div>
            {!unclassifiedCash.isZero() && (
              <p className="mt-2 text-xs text-muted">
                Includes <strong>{formatCurrencyLocale(unclassifiedCash, cur)}</strong> in transfers in transit / unclassified cash movement.
              </p>
            )}
            {incompleteOpeningCoverage && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Records start after the selected period begins. Beginning cash is only the known amount; full-period cash flow is not yet verified.
              </p>
            )}
            {unverified && !incompleteOpeningCoverage && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                {report?.proof_reasons?.includes("opening_position_unproven")
                  ? "Opening balance evidence needs review before cash flow can be verified."
                  : "Cash flow evidence needs review before this report can be verified."}
              </p>
            )}
            {!reconciles && (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Expected ending {formatCurrencyLocale(expectedEnding, cur)} differs from the reported ending by {formatCurrencyLocale(drift.abs(), cur)} — the reported ending is {drift.isPositive() ? "lower" : "higher"} than expected.
              </p>
            )}
          </div>
        );
      })()}

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        {renderSection("Operating Activities", report?.operating || [], "text-[var(--success)]")}
        {renderSection("Investing Activities", report?.investing || [], "text-[var(--accent)]")}
        {renderSection("Financing Activities", report?.financing || [], "text-[var(--warning)]")}
      </div>

      {summary && (
        <div className="card p-5 mb-6">
          <h3 className="font-semibold mb-4">Cash Flow Visualization</h3>
          <SankeyChart operating={report?.operating || []} investing={report?.investing || []} financing={report?.financing || []} title="" height={350} />
        </div>
      )}

      {summary && (
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Summary</h3>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="p-4 rounded-md bg-[var(--success-muted)]">
              <p className="text-xs text-muted uppercase">Operating</p>
              <p className="text-xl font-semibold text-[var(--success)]">{formatCurrencyLocale(summary.operating_activities, report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--accent-muted)]">
              <p className="text-xs text-muted uppercase">Investing</p>
              <p className="text-xl font-semibold text-[var(--accent)]">{formatCurrencyLocale(summary.investing_activities, report?.currency || "SGD")}</p>
            </div>
            <div className="p-4 rounded-md bg-[var(--warning-muted)]">
              <p className="text-xs text-muted uppercase">Financing</p>
              <p className="text-xl font-semibold text-[var(--warning)]">{formatCurrencyLocale(summary.financing_activities, report?.currency || "SGD")}</p>
            </div>
          </div>
        </div>
      )}

      <AccountLineageDrawer target={drillTarget} onClose={() => setDrillTarget(null)} />
    </ReportPageShell>
  );
}

/**
 * The Full package tab of `/reports`. The dimension bar sets the period and the currency of the
 * preview and of a new snapshot. An open snapshot shows its own frozen period. It closes when the
 * bar period changes.
 */
export function PackagePanel({ filters }: { filters: ReportFilters }) {
  const { startDate, endDate: reportDate, currency } = filters;
  const queryClient = useQueryClient();
  const [selectedFrameworkId, setSelectedFrameworkId] = useState<PersonalReportingFrameworkId | null>(null);
  const periodKey = `${startDate}|${reportDate}|${currency ?? ""}`;
  const [openSnapshot, setOpenSnapshot] = useState<{ id: string; periodKey: string } | null>(null);
  const selectedSnapshotId = openSnapshot?.periodKey === periodKey ? openSnapshot.id : null;
  const [lineagePanel, setLineagePanel] = useState<LineagePanelState | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [generatingSnapshot, setGeneratingSnapshot] = useState(false);
  const [downloadingSnapshot, setDownloadingSnapshot] = useState<string | null>(null);

  const {
    contract,
    document: packageDocument,
    packageSnapshots,
    isPackageRefreshing,
    isPackageLoading,
    error,
  } = usePersonalReportPackage(selectedFrameworkId, reportDate, selectedSnapshotId, startDate, currency, filters.ready);

  async function openLineagePanel(shownDocument: PersonalReportPackageDocument, line: PersonalReportPackageTraceabilityLineSummary) {
    setLineagePanel({ line, response: null, isLoading: true, error: null });
    // The preview has no identifiers: read the first page of the line, then ask the graph (#2583 S8).
    let anchor;
    try {
      anchor = await loadLineageAnchorForLine(queryClient, shownDocument, line);
    } catch (err) {
      setLineagePanel({
        line,
        response: null,
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load the evidence of this line.",
      });
      return;
    }
    if (!anchor) {
      setLineagePanel({
        line,
        response: {
          anchor: null,
          nodes: [],
          edges: [],
          blockers: [{ code: "lineage_anchor_missing", message: "No graph-compatible UUID anchor exists for this traceability row." }],
          max_depth: 6,
        },
        isLoading: false,
        error: null,
      });
      return;
    }

    try {
      const response = await apiOperation("get_evidence_lineage_evidence_lineage_get", { query: lineageQuery(anchor) });
      setLineagePanel({ line, response, isLoading: false, error: null });
    } catch (err) {
      setLineagePanel({
        line,
        response: null,
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to load evidence lineage.",
      });
    }
  }

  async function createPackageSnapshot(frameworkId: PersonalReportingFrameworkId) {
    setGeneratingSnapshot(true);
    setSnapshotError(null);
    try {
      const snapshot = await generatePackageSnapshot(frameworkId, reportDate, startDate, currency);
      setOpenSnapshot({ id: snapshot.id, periodKey });
      track(ANALYTICS_EVENTS.REPORT_GENERATED, { framework_id: frameworkId });
      await invalidateReportPackageQueries(queryClient);
    } catch (err) {
      setSnapshotError(err instanceof Error ? err.message : "Failed to generate package snapshot.");
    } finally {
      setGeneratingSnapshot(false);
    }
  }

  function openPackageSnapshot(snapshot: PersonalReportPackageSnapshotSummary) {
    setSnapshotError(null);
    setOpenSnapshot({ id: snapshot.id, periodKey });
    setSelectedFrameworkId(snapshot.framework_id);
  }

  async function downloadPackageSnapshot(snapshot: PersonalReportPackageSnapshotSummary, format: "json" | "csv") {
    setDownloadingSnapshot(`${snapshot.id}:${format}`);
    setSnapshotError(null);
    try {
      const { blob, filename } = await apiOperationDownload(
        "export_personal_report_package_snapshot_reports_package_snapshots__snapshot_id__export_get",
        { path: { snapshot_id: snapshot.id }, query: { format } },
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || `personal-report-package-${snapshot.id}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setSnapshotError(err instanceof Error ? err.message : `Failed to download ${format.toUpperCase()} snapshot.`);
    } finally {
      setDownloadingSnapshot(null);
    }
  }

  if (error) return <div className="text-[var(--error)]">{error}</div>;

  if (!contract) {
    return <PackageLoadingSkeleton />;
  }

  const selectedFrameworkLabel = selectedFrameworkId ? (FRAMEWORK_LABELS[selectedFrameworkId] ?? selectedFrameworkId) : null;
  const frameworkSelection = (
    <PackageFrameworkSelection
      contract={contract}
      selectedFrameworkId={selectedFrameworkId}
      selectedFrameworkLabel={selectedFrameworkLabel}
      reportDate={reportDate}
      startDate={startDate}
      onSelectFramework={(frameworkId) => {
        if (frameworkId !== "personal_us_gaap_like" && frameworkId !== "personal_hkfrs_like") return;
        setOpenSnapshot(null);
        setSelectedFrameworkId(frameworkId);
      }}
    />
  );

  if (!selectedFrameworkId) {
    return (
      <div>
        <PackageCover contract={contract} reportDate={reportDate} startDate={startDate} selectedFrameworkLabel={selectedFrameworkLabel} />
        {frameworkSelection}
        <PackageTableOfContents links={packageTocLinks(contract, false)} />
        <PackageSetupGuidance />
      </div>
    );
  }

  const outputTocLinks = packageTocLinks(packageDocument?.contract ?? contract, true);

  if (isPackageLoading || !packageDocument) {
    return (
      <div>
        <PackageCover contract={contract} reportDate={reportDate} startDate={startDate} selectedFrameworkLabel={selectedFrameworkLabel} />
        {frameworkSelection}
        <PackageTableOfContents links={outputTocLinks} />
        <PackageLoadingSkeleton />
      </div>
    );
  }

  const evidenceReferences = evidenceBundleReferences(packageDocument.framework_policy);
  const canGenerateSnapshot = !generatingSnapshot && !isPackageRefreshing;
  const shownContext = packageDocument.lifecycle === "frozen" || isPackageRefreshing ? packageDocument.context : null;

  return (
    <div aria-busy={isPackageRefreshing || undefined}>
      {isPackageRefreshing && shownContext ? (
        <div role="status" aria-live="polite" className="card mb-4 p-3 text-sm text-muted">
          {`Loading the package for ${startDate} to ${reportDate}. The report below still shows ${shownContext.start_date} to ${shownContext.end_date}.`}
        </div>
      ) : null}

      <PackageCover
        contract={contract}
        reportDate={shownContext?.end_date ?? reportDate}
        startDate={shownContext?.start_date ?? startDate}
        asOfDate={shownContext?.as_of_date ?? reportDate}
        selectedFrameworkLabel={selectedFrameworkLabel}
      />
      {frameworkSelection}
      <PackageTableOfContents links={outputTocLinks} />
      <PackageSnapshotsCard
        snapshots={packageSnapshots}
        snapshotError={snapshotError}
        canGenerate={canGenerateSnapshot}
        generating={generatingSnapshot}
        downloading={downloadingSnapshot}
        selectedSnapshotId={selectedSnapshotId}
        onGenerate={() => void createPackageSnapshot(selectedFrameworkId)}
        onOpen={openPackageSnapshot}
        onDownload={downloadPackageSnapshot}
      />

      <section className="card p-5 mb-6" aria-label="Package document identity">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Package Document</h2>
            <p className="mt-2 text-sm text-muted">
              {packageDocument.lifecycle === "frozen"
                ? `Frozen snapshot ${packageDocument.snapshot_id}`
                : "Live preview. Generate a snapshot to freeze these exact inputs and totals."}
            </p>
          </div>
          <span className="badge badge-muted">{packageDocument.status === "trusted" ? "Trusted" : "Draft"}</span>
        </div>
      </section>

      <PackageReadinessSection readiness={packageDocument.readiness} />
      <PackageInputManifestSection coverage={packageDocument.readiness.input_coverage} document={packageDocument} />
      <PackageFrameworkPolicySection policy={packageDocument.framework_policy} />
      <PackageSectionCards sections={packageDocument.sections} includeRestricted={packageDocument.context.include_restricted} />
      <PackageAnnualizedScheduleSection schedule={packageDocument.sections.annualized_income_long_term} />
      <PackageNotesSection notes={packageDocument.sections.notes} />
      <PackageTraceabilitySection
        appendix={packageDocument.sections.traceability_appendix}
        document={packageDocument}
        onTrace={(line) => void openLineagePanel(packageDocument, line)}
      />
      <PackageExportContractSection contract={packageDocument.contract} policy={packageDocument.framework_policy} evidenceReferences={evidenceReferences} />

      {lineagePanel ? <LineagePanelModal panel={lineagePanel} onClose={() => setLineagePanel(null)} /> : null}
    </div>
  );
}
