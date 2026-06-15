"use client";

import { useState } from "react";

import { track, ANALYTICS_EVENTS } from "@/lib/analytics";
import {
  PackageCover,
  PackageFrameworkSelection,
  PackageLoadingSkeleton,
  PackageSetupGuidance,
  PackageTableOfContents,
} from "@/components/reports/package/PackageChrome";
import {
  PackageFrameworkPolicySection,
  PackageReadinessSection,
  PackageSourceTrustSection,
} from "@/components/reports/package/PackageReadinessSections";
import {
  PackageAnnualizedScheduleSection,
  PackageExportContractSection,
  PackageNotesSection,
  PackageSectionCards,
} from "@/components/reports/package/PackageScheduleSections";
import { PackageSnapshotsCard } from "@/components/reports/package/PackageSnapshotsCard";
import {
  LineagePanelModal,
  PackageTraceabilitySection,
} from "@/components/reports/package/PackageTraceability";
import {
  FRAMEWORK_LABELS,
  evidenceBundleReferences,
  lineageAnchorForLine,
  packageTocLinks,
  type LineagePanelState,
} from "@/components/reports/package/shared";
import {
  generatePackageSnapshot,
  isValidReportDate,
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import { apiDownload, apiFetch } from "@/lib/api";
import { formatDateInput } from "@/lib/date";
import { lineageUrl } from "@/lib/lineage";
import type {
  EvidenceLineageResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
} from "@/lib/types";

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
      // EPIC-022 AC22.18.3 (#1109): instrument report-package generation. The
      // framework id is a safe, non-PII selector (e.g. personal_us_gaap_like).
      track(ANALYTICS_EVENTS.REPORT_GENERATED, { framework_id: selectedFrameworkId });
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

  const selectedFrameworkLabel = selectedFrameworkId
    ? (FRAMEWORK_LABELS[selectedFrameworkId] ?? selectedFrameworkId)
    : null;

  const frameworkSelection = (
    <PackageFrameworkSelection
      contract={contract}
      selectedFrameworkId={selectedFrameworkId}
      selectedFrameworkLabel={selectedFrameworkLabel}
      reportDate={reportDate}
      onSelectFramework={setSelectedFrameworkId}
      onReportDateChange={setReportDate}
    />
  );

  if (!selectedFrameworkId) {
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
        <PackageTableOfContents links={packageTocLinks(contract, false)} />
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

      <PackageSnapshotsCard
        snapshots={packageSnapshots}
        snapshotError={snapshotError}
        canGenerate={canGenerateSnapshot}
        generating={generatingSnapshot}
        downloading={downloadingSnapshot}
        onGenerate={createPackageSnapshot}
        onDownload={downloadPackageSnapshot}
      />

      <PackageReadinessSection readiness={readiness} />

      {readiness.source_trust_summary ? (
        <PackageSourceTrustSection summary={readiness.source_trust_summary} />
      ) : null}

      <PackageFrameworkPolicySection policy={frameworkPolicy} />

      <PackageSectionCards sections={contract.sections} />

      <PackageAnnualizedScheduleSection schedule={annualizedSchedule} />

      <PackageNotesSection notes={packageNotes} />

      <PackageTraceabilitySection
        appendix={traceabilityAppendix}
        onTrace={(line) => void openLineagePanel(line)}
      />

      <PackageExportContractSection
        contract={contract}
        policy={frameworkPolicy}
        evidenceReferences={evidenceReferences}
      />

      {lineagePanel ? (
        <LineagePanelModal
          panel={lineagePanel}
          onClose={() => setLineagePanel(null)}
        />
      ) : null}
    </div>
  );
}
