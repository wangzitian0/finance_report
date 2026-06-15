"use client";

import { useState } from "react";

import { apiDownload, apiFetch } from "@/lib/api";
import { formatDateInput } from "@/lib/date";
import { lineageUrl } from "@/lib/lineage";
import {
  generatePackageSnapshot,
  isValidReportDate,
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import type {
  EvidenceLineageResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
} from "@/lib/types";

import {
  EvidenceLineagePanel,
  PackageAnnualizedScheduleSection,
  PackageContractSections,
  PackageCover,
  PackageExportContractSection,
  PackageFrameworkPolicySection,
  PackageFrameworkSelection,
  PackageLoadingSkeleton,
  PackageNotesSection,
  PackageReadinessSection,
  PackageSetupGuidance,
  PackageSnapshotsSection,
  PackageSourceTrustSection,
  PackageTableOfContents,
  PackageTraceabilityAppendixSection,
} from "./_components/PackageSections";
import {
  FRAMEWORK_LABELS,
  evidenceBundleReferences,
  lineageAnchorForLine,
  packageTocLinks,
} from "./_components/helpers";

type LineagePanelState = {
  line: PersonalReportPackageTraceabilityLine;
  response: EvidenceLineageResponse | null;
  isLoading: boolean;
  error: string | null;
};

export default function PersonalReportPackagePage() {
  const [selectedFrameworkId, setSelectedFrameworkId] = useState<string | null>(
    null,
  );
  const [reportDate, setReportDate] = useState(() => formatDateInput(new Date()));
  const [lineagePanel, setLineagePanel] = useState<LineagePanelState | null>(
    null,
  );
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [generatingSnapshot, setGeneratingSnapshot] = useState(false);
  const [downloadingSnapshot, setDownloadingSnapshot] = useState<string | null>(
    null,
  );
  const {
    contract,
    readiness,
    frameworkPolicy,
    annualizedSchedule,
    packageNotes,
    traceabilityAppendix,
    packageSnapshots,
    refetchPackageSnapshots,
    isPackageLoading,
    error,
  } = usePersonalReportPackage(selectedFrameworkId, reportDate);

  function handleReportDateChange(nextReportDate: string) {
    setReportDate(nextReportDate);
  }

  async function openLineagePanel(line: PersonalReportPackageTraceabilityLine) {
    setLineagePanel({ line, response: null, isLoading: true, error: null });
    const anchor = lineageAnchorForLine(line);
    if (!anchor) {
      setLineagePanel({
        line,
        response: {
          anchor: null,
          nodes: [],
          edges: [],
          blockers: [
            {
              code: "lineage_anchor_missing",
              message: "No graph-compatible UUID anchor exists for this traceability row.",
            },
          ],
          max_depth: 6,
        },
        isLoading: false,
        error: null,
      });
      return;
    }

    try {
      const response = await apiFetch<EvidenceLineageResponse>(
        lineageUrl(anchor),
      );
      setLineagePanel({ line, response, isLoading: false, error: null });
    } catch (err) {
      setLineagePanel({
        line,
        response: null,
        isLoading: false,
        error:
          err instanceof Error ? err.message : "Failed to load evidence lineage.",
      });
    }
  }

  async function createPackageSnapshot() {
    if (!selectedFrameworkId || !isValidReportDate(reportDate)) return;
    setGeneratingSnapshot(true);
    setSnapshotError(null);
    try {
      await generatePackageSnapshot(selectedFrameworkId, reportDate);
      await refetchPackageSnapshots();
    } catch (err) {
      setSnapshotError(
        err instanceof Error ? err.message : "Failed to generate package snapshot.",
      );
    } finally {
      setGeneratingSnapshot(false);
    }
  }

  async function downloadPackageSnapshot(
    snapshot: PersonalReportPackageSnapshotSummary,
    format: "json" | "csv",
  ) {
    setDownloadingSnapshot(`${snapshot.id}:${format}`);
    setSnapshotError(null);
    try {
      const { blob, filename } = await apiDownload(
        `/api/reports/package/snapshots/${snapshot.id}/export?format=${format}`,
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
      setSnapshotError(
        err instanceof Error ? err.message : `Failed to download ${format.toUpperCase()} snapshot.`,
      );
    } finally {
      setDownloadingSnapshot(null);
    }
  }

  if (error) {
    return <div className="p-6 text-[var(--error)]">{error}</div>;
  }

  if (!contract) {
    return <div className="p-6 text-muted">Loading package contract...</div>;
  }

  const frameworkButtons = contract.supported_frameworks.map((frameworkId) => {
    const isSelected = selectedFrameworkId === frameworkId;
    return (
      <button
        key={frameworkId}
        type="button"
        className={`${isSelected ? "btn-primary" : "btn-secondary"} text-sm`}
        aria-pressed={isSelected}
        onClick={() => setSelectedFrameworkId(frameworkId)}
      >
        {FRAMEWORK_LABELS[frameworkId] ?? frameworkId}
      </button>
    );
  });

  const selectedFrameworkLabel = selectedFrameworkId
    ? (FRAMEWORK_LABELS[selectedFrameworkId] ?? selectedFrameworkId)
    : null;

  const frameworkSelection = (
    <PackageFrameworkSelection
      contract={contract}
      reportDate={reportDate}
      selectedFrameworkId={selectedFrameworkId}
      selectedFrameworkLabel={selectedFrameworkLabel}
      frameworkButtons={frameworkButtons}
      onReportDateChange={handleReportDateChange}
    />
  );

  if (!selectedFrameworkId) {
    const setupTocLinks = packageTocLinks(contract, false);
    return (
      <div className="p-6">
        <div className="page-header">
          <h1 className="page-title">Personal Report Package</h1>
          <p className="page-description">{contract.package_id}</p>
        </div>
        <PackageCover
          contract={contract}
          reportDate={reportDate}
          selectedFrameworkLabel={selectedFrameworkLabel}
        />
        {frameworkSelection}
        <PackageTableOfContents links={setupTocLinks} />
        <PackageSetupGuidance />
      </div>
    );
  }

  const outputTocLinks = packageTocLinks(contract, true);

  if (
    isPackageLoading ||
    !readiness ||
    !annualizedSchedule ||
    !packageNotes ||
    !traceabilityAppendix ||
    !frameworkPolicy
  ) {
    return (
      <div className="p-6">
        <div className="page-header">
          <h1 className="page-title">Personal Report Package</h1>
          <p className="page-description">{contract.package_id}</p>
        </div>
        <PackageCover
          contract={contract}
          reportDate={reportDate}
          selectedFrameworkLabel={selectedFrameworkLabel}
        />
        {frameworkSelection}
        <PackageTableOfContents links={outputTocLinks} />
        <PackageLoadingSkeleton />
      </div>
    );
  }

  const evidenceReferences = evidenceBundleReferences(frameworkPolicy);
  const canGenerateSnapshot = Boolean(
    selectedFrameworkId && isValidReportDate(reportDate) && !generatingSnapshot,
  );

  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">Personal Report Package</h1>
        <p className="page-description">{contract.package_id}</p>
      </div>

      <PackageCover
        contract={contract}
        reportDate={reportDate}
        selectedFrameworkLabel={selectedFrameworkLabel}
      />

      {frameworkSelection}

      <PackageTableOfContents links={outputTocLinks} />

      <PackageSnapshotsSection
        packageSnapshots={packageSnapshots}
        snapshotError={snapshotError}
        generatingSnapshot={generatingSnapshot}
        canGenerateSnapshot={canGenerateSnapshot}
        downloadingSnapshot={downloadingSnapshot}
        onGenerateSnapshot={createPackageSnapshot}
        onPrint={() => window.print()}
        onDownloadSnapshot={downloadPackageSnapshot}
      />

      <PackageReadinessSection readiness={readiness} />

      <PackageSourceTrustSection readiness={readiness} />

      <PackageFrameworkPolicySection frameworkPolicy={frameworkPolicy} />

      <PackageContractSections contract={contract} />

      <PackageAnnualizedScheduleSection annualizedSchedule={annualizedSchedule} />

      <PackageNotesSection packageNotes={packageNotes} />

      <PackageTraceabilityAppendixSection
        traceabilityAppendix={traceabilityAppendix}
        onOpenLineagePanel={(line) => void openLineagePanel(line)}
      />

      <PackageExportContractSection
        contract={contract}
        frameworkPolicy={frameworkPolicy}
        evidenceReferences={evidenceReferences}
      />
      {lineagePanel ? (
        <EvidenceLineagePanel
          line={lineagePanel.line}
          response={lineagePanel.response}
          isLoading={lineagePanel.isLoading}
          error={lineagePanel.error}
          onClose={() => setLineagePanel(null)}
        />
      ) : null}
    </div>
  );
}
