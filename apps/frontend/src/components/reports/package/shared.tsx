import { formatCurrencyLocale } from "@/lib/audit/money";
import { anchorFromIdentifiers, type LineageAnchor } from "@/lib/lineage";
import type {
  EvidenceLineageResponse,
  FrameworkPolicyResult,
  MoneyValue,
  PersonalReportPackageContractResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
} from "@/lib/types";
import { sourceClassLabel } from "@/lib/statusLabels";

export const FRAMEWORK_LABELS: Record<string, string> = {
  personal_us_gaap_like: "US-like",
  personal_hkfrs_like: "HK-like",
};

export type LineagePanelState = {
  line: PersonalReportPackageTraceabilityLine;
  response: EvidenceLineageResponse | null;
  isLoading: boolean;
  error: string | null;
};

export type PackageTocLink = {
  id: string;
  label: string;
  status?: string;
};

export function sectionAnchorId(sectionId: string): string {
  return `package-section-${sectionId}`;
}

export function packageTocLinks(
  contract: PersonalReportPackageContractResponse,
  includeOutputSections: boolean,
): PackageTocLink[] {
  const links: PackageTocLink[] = [
    { id: "package-framework-selection", label: "Reporting Framework" },
  ];
  if (includeOutputSections) {
    links.push(
      { id: "package-readiness", label: "Report Readiness" },
      { id: "package-source-trust", label: "Evidence Coverage" },
      { id: "package-framework-policy", label: "Reporting Basis" },
    );
  }
  links.push(
    ...contract.sections.map((section) => ({
      id: sectionAnchorId(section.section_id),
      label: section.label,
      status: section.status,
    })),
  );
  if (includeOutputSections) {
    links.push(
      { id: "package-traceability-detail", label: "Traceability Summary" },
      { id: "package-export-contract", label: "Export Options" },
    );
  }
  return links;
}

export function formatScheduleCurrency(
  value: MoneyValue,
  currency: string,
): string {
  return formatCurrencyLocale(value, currency, "en-US", {
    maximumFractionDigits: 0,
  }).replace(/\u00a0/g, " ");
}

export function renderCsv(values?: string[]): string {
  return values && values.length ? values.join(", ") : "none";
}

export function renderSourceClasses(values?: string[]): string {
  return values && values.length ? values.map(sourceClassLabel).join(", ") : "none";
}

export function renderAnchorDetail(primary: string, identifiers?: string[]) {
  return (
    <>
      <p className="mt-1 text-xs text-muted">{primary}</p>
      {identifiers?.length ? (
        <p className="mt-1 max-w-xs break-words font-mono text-[11px] text-muted">
          {identifiers.join(", ")}
        </p>
      ) : null}
    </>
  );
}

export function evidenceBundleReferences(
  policyResult: FrameworkPolicyResult,
): string[] {
  const anchors = [
    ...policyResult.decisions.flatMap((decision) => decision.evidence_anchors),
    ...policyResult.gaps.flatMap((gap) => gap.evidence_anchors),
  ];
  return Array.from(
    new Set(
      anchors.map((anchor) => `${anchor.anchor_type}:${anchor.source_id}`),
    ),
  ).sort();
}

export function formatSnapshotTimestamp(value?: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function snapshotDownloadLabel(
  snapshot: PersonalReportPackageSnapshotSummary,
  format: "JSON" | "CSV",
): string {
  const framework =
    FRAMEWORK_LABELS[snapshot.framework_id] ?? snapshot.framework_id;
  return `Download ${format} snapshot ${snapshot.id} for ${framework} ${snapshot.start_date} to ${snapshot.end_date}`;
}

export function lineageAnchorForLine(
  line: PersonalReportPackageTraceabilityLine,
): LineageAnchor | null {
  return anchorFromIdentifiers([
    ...(line.ledger_anchor.identifiers ?? []),
    ...(line.source_anchor.identifiers ?? []),
  ]);
}
