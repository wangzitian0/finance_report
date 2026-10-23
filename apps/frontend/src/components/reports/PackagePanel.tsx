"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { track, ANALYTICS_EVENTS } from "@/lib/analytics";
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
import {
  generatePackageSnapshot,
  invalidateReportPackageQueries,
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import type { ReportFilters } from "@/hooks/useReportFilters";
import { apiOperation, apiOperationDownload } from "@/lib/api-client";
import { lineageQuery } from "@/lib/lineage";
import { loadLineageAnchorForLine } from "@/lib/packageEvidence";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLineSummary,
  PersonalReportingFrameworkId,
} from "@/lib/types";

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
    return (
      <div role="status" aria-label="Loading report package" aria-busy="true" aria-live="polite" className="text-muted">
        Loading package document...
      </div>
    );
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
      <PackageSectionCards sections={packageDocument.sections} />
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
