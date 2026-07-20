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
  PackageInputManifestSection,
  PackageReadinessSection,
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
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import { apiOperation, apiOperationDownload } from "@/lib/api-client";
import { formatDateInput } from "@/lib/date";
import { lineageQuery } from "@/lib/lineage";
import { isValidReportDate } from "@/lib/reportPackage";
import type {
  EvidenceLineageResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
  PersonalReportingFrameworkId,
} from "@/lib/types";

export default function PersonalReportPackagePage() {
  const [selectedFrameworkId, setSelectedFrameworkId] =
    useState<PersonalReportingFrameworkId | null>(null);
  const [reportDate, setReportDate] = useState(() =>
    formatDateInput(new Date()),
  );
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(
    null,
  );
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
    document: packageDocument,
    packageSnapshots,
    refetchPackageSnapshots,
    isPackageLoading,
    error,
  } = usePersonalReportPackage(
    selectedFrameworkId,
    reportDate,
    selectedSnapshotId,
  );

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
              message:
                "No graph-compatible UUID anchor exists for this traceability row.",
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
      const response = await apiOperation(
        "get_evidence_lineage_evidence_lineage_get",
        {
          query: lineageQuery(anchor),
        },
      );
      setLineagePanel({ line, response, isLoading: false, error: null });
    } catch (err) {
      setLineagePanel({
        line,
        response: null,
        isLoading: false,
        error:
          err instanceof Error
            ? err.message
            : "Failed to load evidence lineage.",
      });
    }
  }

  async function createPackageSnapshot() {
    if (!selectedFrameworkId || !isValidReportDate(reportDate)) return;
    setGeneratingSnapshot(true);
    setSnapshotError(null);
    try {
      const snapshot = await generatePackageSnapshot(
        selectedFrameworkId,
        reportDate,
      );
      setSelectedSnapshotId(snapshot.id);
      // EPIC-022 AC22.18.3 (#1109): instrument report-package generation. The
      // framework id is a safe, non-PII selector (e.g. personal_us_gaap_like).
      track(ANALYTICS_EVENTS.REPORT_GENERATED, {
        framework_id: selectedFrameworkId,
      });
      await refetchPackageSnapshots();
    } catch (err) {
      setSnapshotError(
        err instanceof Error
          ? err.message
          : "Failed to generate package snapshot.",
      );
    } finally {
      setGeneratingSnapshot(false);
    }
  }

  function openPackageSnapshot(snapshot: PersonalReportPackageSnapshotSummary) {
    setSnapshotError(null);
    setSelectedSnapshotId(snapshot.id);
    setSelectedFrameworkId(snapshot.framework_id);
    setReportDate(snapshot.end_date);
  }

  async function downloadPackageSnapshot(
    snapshot: PersonalReportPackageSnapshotSummary,
    format: "json" | "csv",
  ) {
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
      link.download =
        filename || `personal-report-package-${snapshot.id}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setSnapshotError(
        err instanceof Error
          ? err.message
          : `Failed to download ${format.toUpperCase()} snapshot.`,
      );
    } finally {
      setDownloadingSnapshot(null);
    }
  }

  if (error) {
    return <div className="p-6 text-[var(--error)]">{error}</div>;
  }

  if (!contract) {
    return (
      <div
        role="status"
        aria-label="Loading report package"
        aria-busy="true"
        aria-live="polite"
        className="p-6 text-muted"
      >
        Loading package document...
      </div>
    );
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
      onSelectFramework={(frameworkId) => {
        if (
          frameworkId !== "personal_us_gaap_like" &&
          frameworkId !== "personal_hkfrs_like"
        )
          return;
        setSelectedSnapshotId(null);
        setSelectedFrameworkId(frameworkId);
      }}
      onReportDateChange={(nextDate) => {
        setSelectedSnapshotId(null);
        setReportDate(nextDate);
      }}
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

  const outputTocLinks = packageTocLinks(
    packageDocument?.contract ?? contract,
    true,
  );

  if (isPackageLoading || !packageDocument) {
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

  const evidenceReferences = evidenceBundleReferences(
    packageDocument.framework_policy,
  );
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
        selectedSnapshotId={selectedSnapshotId}
        onGenerate={createPackageSnapshot}
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
          <span className="badge badge-muted">
            {packageDocument.status === "trusted" ? "Trusted" : "Draft"}
          </span>
        </div>
      </section>

      <PackageReadinessSection readiness={packageDocument.readiness} />

      <PackageInputManifestSection
        coverage={packageDocument.readiness.input_coverage}
        manifest={packageDocument.input_manifest}
      />

      <PackageFrameworkPolicySection
        policy={packageDocument.framework_policy}
      />

      <PackageSectionCards sections={packageDocument.sections} />

      <PackageAnnualizedScheduleSection
        schedule={packageDocument.sections.annualized_income_long_term}
      />

      <PackageNotesSection notes={packageDocument.sections.notes} />

      <PackageTraceabilitySection
        appendix={packageDocument.sections.traceability_appendix}
        onTrace={(line) => void openLineagePanel(line)}
      />

      <PackageExportContractSection
        contract={packageDocument.contract}
        policy={packageDocument.framework_policy}
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
