import Link from "next/link";
import { Download, FileJson, Network, Printer, Save, X } from "lucide-react";

import { SkeletonBlock } from "@/components/ui";
import { formatCurrencyLocale } from "@/lib/audit/money";
import {
  anchorFromIdentifiers,
  nodeDisplayTitle,
  nodeLabel,
  nodeSourceHref,
  type LineageAnchor,
} from "@/lib/lineage";
import type {
  AnnualizedIncomeScheduleResponse,
  EvidenceLineageResponse,
  FrameworkPolicyResult,
  MoneyValue,
  PersonalReportPackageContractResponse,
  PersonalReportPackageInputCoverage,
  PersonalReportPackageNotesResponse,
  PersonalReportPackageReadinessResponse,
  PersonalReportPackageSections,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityLine,
  PersonalReportPackageTraceabilityResponse,
  PersonalReportPackageTraceManifestEntry,
} from "@/lib/types";
import {
  countLabel,
  humanizeIdentifier,
  sourceClassLabel,
} from "@/lib/statusLabels";

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
      { id: "package-input-manifest", label: "Authority Coverage" },
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
    ...(policyResult.decisions ?? []).flatMap((decision) => decision.evidence_anchors ?? []),
    ...(policyResult.gaps ?? []).flatMap((gap) => gap.evidence_anchors ?? []),
  ].filter((anchor): anchor is NonNullable<typeof anchor> => Boolean(anchor));
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

export function PackageCover({
  contract,
  reportDate,
  startDate,
  asOfDate = reportDate,
  selectedFrameworkLabel,
}: {
  contract: PersonalReportPackageContractResponse;
  reportDate: string;
  startDate: string;
  asOfDate?: string;
  selectedFrameworkLabel: string | null;
}) {
  return (
    <section aria-label="Report package cover" className="card p-6 mb-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">
            Personal financial-report package
          </p>
          <h2 className="mt-2 text-2xl font-semibold">Personal Report Package</h2>
          <p className="mt-2 font-mono text-sm text-muted">
            {contract.package_id}
          </p>
        </div>
        <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:min-w-[28rem]">
          <div>
            <dt className="text-xs text-muted">Framework</dt>
            <dd className="mt-1 font-semibold">
              {selectedFrameworkLabel ?? "Framework not selected"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Balances as of</dt>
            <dd className="mt-1 font-mono text-xs">{asOfDate}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Report Period</dt>
            <dd className="mt-1 font-mono text-xs">
              {startDate} to {reportDate}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Package Version</dt>
            <dd className="mt-1 font-mono text-xs">{contract.version}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

export function PackageTableOfContents({ links }: { links: PackageTocLink[] }) {
  return (
    <nav
      aria-label="Report package table of contents"
      className="card p-5 mb-6"
    >
      <h2 className="font-semibold">Table of Contents</h2>
      <ol className="mt-4 grid gap-2 text-sm md:grid-cols-2">
        {links.map((link) => (
          <li key={link.id}>
            <a
              href={`#${link.id}`}
              aria-label={link.status ? `${link.label} ${link.status}` : link.label}
              className="flex items-center justify-between gap-3 rounded-control border border-[var(--border)] px-3 py-2 text-[var(--foreground)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
            >
              <span>{link.label}</span>
              {link.status ? (
                <span className="badge badge-muted">{link.status}</span>
              ) : null}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PackageSetupGuidance() {
  return (
    <section aria-label="Package setup guidance" className="card p-5 mb-6">
      <h2 className="font-semibold">Package Setup</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {[
          ["1", "Choose a framework", "Select US-like or HK-like before package output is loaded."],
          ["2", "Choose the period", "Set the start and end dates. Account balances are shown at the period end."],
          ["3", "Review readiness", "Package blockers appear before statements and schedules."],
        ].map(([step, title, description]) => (
          <div key={step} className="rounded border border-[var(--border)] p-3">
            <p className="font-mono text-xs text-muted">Step {step}</p>
            <p className="mt-2 font-medium">{title}</p>
            <p className="mt-1 text-sm text-muted">{description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PackageLoadingSkeleton() {
  return (
    <section
      role="status"
      aria-label="Loading report package"
      aria-busy="true"
      aria-live="polite"
      className="space-y-4"
    >
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="card p-4">
            <SkeletonBlock className="h-3 w-20" />
            <SkeletonBlock className="mt-3 h-6 w-16" />
          </div>
        ))}
      </div>
      <div className="card p-5">
        <SkeletonBlock className="h-5 w-48" />
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="rounded border border-[var(--border)] p-3">
              <SkeletonBlock className="h-4 w-3/5" />
              <SkeletonBlock className="mt-3 h-3 w-full" />
              <SkeletonBlock className="mt-2 h-3 w-4/5" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function PackageFrameworkSelection({
  contract,
  selectedFrameworkId,
  selectedFrameworkLabel,
  reportDate,
  startDate,
  periodError,
  onStartDateChange,
  onSelectFramework,
  onReportDateChange,
}: {
  contract: PersonalReportPackageContractResponse;
  selectedFrameworkId: string | null;
  selectedFrameworkLabel: string | null;
  reportDate: string;
  startDate: string;
  periodError: string | null;
  onStartDateChange: (startDate: string) => void;
  onSelectFramework: (frameworkId: string) => void;
  onReportDateChange: (reportDate: string) => void;
}) {
  const supported = contract.supported_frameworks ?? [];
  const frameworkButtons = supported.map((frameworkId) => {
    const isSelected = selectedFrameworkId === frameworkId;
    return (
      <button
        key={frameworkId}
        type="button"
        className={`${isSelected ? "btn-primary" : "btn-secondary"} text-sm`}
        aria-pressed={isSelected}
        onClick={() => onSelectFramework(frameworkId)}
      >
        {FRAMEWORK_LABELS[frameworkId] ?? frameworkId}
      </button>
    );
  });

  return (
    <section id="package-framework-selection" className="card p-5 mb-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Reporting Framework</h2>
          <p className="mt-2 text-sm text-muted">
            {selectedFrameworkId
              ? `${selectedFrameworkLabel} selected for this package.`
              : "Select a framework before package output is loaded."}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted uppercase">Period start</span>
            <input
              type="date"
              value={startDate}
              onChange={(event) => onStartDateChange(event.target.value)}
              className="input w-auto"
              aria-label="Package period start"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted uppercase">Period end (report date)</span>
            <input
              type="date"
              value={reportDate}
              onChange={(event) => onReportDateChange(event.target.value)}
              className="input w-auto"
              aria-label="Package report date"
            />
          </label>
          <div className="flex flex-wrap gap-2">{frameworkButtons}</div>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted">
        Choose any period, such as March 1–31. Account balances use the period
        end. The default covers the previous year until you change the start date.
      </p>
      {periodError && (
        <p role="alert" className="mt-3 text-sm text-[var(--error)]">{periodError}</p>
      )}
      {selectedFrameworkId ? (
        <>
          <dl className="mt-5 grid gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Reporting basis</dt>
              <dd className="mt-1 font-semibold">{selectedFrameworkLabel}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Report period</dt>
              <dd className="mt-1 font-medium">
                {startDate} to {reportDate}
              </dd>
            </div>
          </dl>
          <details className="mt-4 rounded border border-[var(--border)] p-3 text-sm print:hidden">
            <summary className="cursor-pointer font-medium">Framework setup audit details</summary>
            <dl className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <dt className="text-xs text-muted">Selected Framework</dt>
                <dd className="mt-1 font-mono text-xs">{selectedFrameworkId}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">Supported Frameworks</dt>
                <dd className="mt-1 font-mono text-xs">
                  {(contract.supported_frameworks ?? []).join(", ")}
                </dd>
              </div>
            </dl>
          </details>
        </>
      ) : null}
    </section>
  );
}

export function PackageReadinessSection({
  readiness,
}: {
  readiness: PersonalReportPackageReadinessResponse;
}) {
  const blockers = readiness.blockers ?? [];
  const inputCoverage = readiness.input_coverage ?? {
    manifest_decision_count: 0,
    authoritative_input_count: 0,
    unproven_input_count: 0,
  };

  return (
    <section id="package-readiness" className="card p-5 mb-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Report Readiness</h2>
          <p className="mt-2 text-sm text-muted">
            {readiness.state === "blocked"
              ? `${readiness.blocking_count} blocker${readiness.blocking_count === 1 ? "" : "s"} must be resolved before package output is trusted.`
              : `Current package state is ${readiness.label.toLowerCase()}.`}
          </p>
        </div>
        <Link className="badge badge-muted" href={readiness.action_href}>
          {readiness.label}
        </Link>
      </div>
      <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted">Authority Decisions</dt>
          <dd className="mt-1 font-semibold">
            {inputCoverage.manifest_decision_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Authoritative Inputs</dt>
          <dd className="mt-1 font-semibold">
            {inputCoverage.authoritative_input_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Unproven Inputs</dt>
          <dd className="mt-1 font-semibold">
            {inputCoverage.unproven_input_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Blockers</dt>
          <dd className="mt-1 font-semibold">{readiness.blocking_count}</dd>
        </div>
      </dl>
      {blockers.length ? (
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {blockers.map((blocker) => (
            <article
              key={blocker.code}
              className="border border-[var(--border)] rounded p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{blocker.label}</p>
                </div>
                <Link
                  className="badge badge-muted"
                  href={blocker.action_href}
                >
                  {blocker.count}
                </Link>
              </div>
              <p className="mt-3 text-sm text-muted">{blocker.reason}</p>
            </article>
          ))}
        </div>
      ) : null}
      <details className="mt-5 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Readiness audit details</summary>
        <dl className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <dt className="text-xs text-muted">Package state</dt>
            <dd className="mt-1 font-mono text-xs">{readiness.state}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Action href</dt>
            <dd className="mt-1 font-mono text-xs">{readiness.action_href}</dd>
          </div>
        </dl>
        {blockers.length ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {blockers.map((blocker) => (
              <article key={blocker.code} className="rounded border border-[var(--border)] p-3">
                <p className="font-mono text-xs">{blocker.code}</p>
                <dl className="mt-2 space-y-1 text-xs">
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted">Blocker code</dt>
                    <dd className="font-mono text-right">{blocker.code}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted">Severity</dt>
                    <dd className="font-mono text-right">{blocker.severity}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted">Action href</dt>
                    <dd className="font-mono text-right">{blocker.action_href}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        ) : null}
      </details>
    </section>
  );
}

export function PackageInputManifestSection({
  coverage,
  manifest,
}: {
  coverage: PersonalReportPackageInputCoverage;
  manifest: PersonalReportPackageTraceManifestEntry[];
}) {
  return (
    <section id="package-input-manifest" className="card p-5 mb-6" aria-label="Authority Coverage">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Authority Coverage</h2>
          <p className="mt-2 text-sm text-muted">
            Trust comes from the current decision graph pinned into this document, not a source label.
          </p>
        </div>
        <span className="badge badge-muted">{coverage.manifest_decision_count} decisions</span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <CoverageMetric label="Authoritative inputs" value={coverage.authoritative_input_count} />
        <CoverageMetric label="Unproven inputs" value={coverage.unproven_input_count} />
      </dl>
      <details className="mt-4 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Authority manifest audit details</summary>
        <div className="mt-3 space-y-2 font-mono text-xs">
          {manifest.length ? manifest.map((entry) => (
            <p key={entry.decision_id}>
              {entry.decision_id} {entry.target_kind}:{entry.target_id}@{entry.target_version}
            </p>
          )) : <p>No authority decisions are pinned for this document.</p>}
        </div>
      </details>
    </section>
  );
}

function CoverageMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-[var(--border)] p-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  );
}

export function PackageFrameworkPolicySection({
  policy,
}: {
  policy: FrameworkPolicyResult;
}) {
  const frameworkLabel = FRAMEWORK_LABELS[policy.framework_id] ?? humanizeIdentifier(policy.framework_id);
  const gaps = policy.gaps ?? [];
  const decisions = policy.decisions ?? [];
  const requiredStatements = policy.required_statements ?? [];

  return (
    <section id="package-framework-policy" className="card p-5 mb-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Reporting Basis</h2>
          <p className="mt-2 text-sm text-muted">
            {frameworkLabel} basis for the selected report period.
          </p>
        </div>
        <span className="badge badge-muted">
          {frameworkLabel}
        </span>
      </div>
      <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted">Reporting basis</dt>
          <dd className="mt-1 font-semibold">{frameworkLabel}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Required statements</dt>
          <dd className="mt-1 font-semibold">
            {requiredStatements.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Decisions</dt>
          <dd className="mt-1 font-semibold">
            {decisions.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Reporting gaps</dt>
          <dd className="mt-1 font-semibold">
            {gaps.length}
          </dd>
        </div>
      </dl>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        {decisions.map((decision) => (
          <article
            key={`${decision.domain}:${decision.line_mappings.balance_sheet ?? decision.presentation}`}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{humanizeIdentifier(decision.domain)}</p>
                <p className="mt-1 text-sm text-muted">{decision.classification}</p>
              </div>
              <span className="badge badge-muted">
                {decision.review_state === "accepted" ? "Accepted" : humanizeIdentifier(decision.review_state)}
              </span>
            </div>
            <p className="mt-3 text-sm text-muted">{decision.presentation}</p>
          </article>
        ))}
        {gaps.map((gap) => (
          <article
            key={`${gap.code}:${gap.fact_id}`}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{humanizeIdentifier(gap.domain)}</p>
                <p className="mt-1 text-sm text-muted">{gap.reason}</p>
              </div>
              <span className="badge badge-warning">
                {gap.blocker ? "Blocks trusted output" : "Needs review"}
              </span>
            </div>
            {gap.remediation ? (
              <p className="mt-3 text-sm text-muted">{gap.remediation}</p>
            ) : null}
          </article>
        ))}
      </div>
      <details className="mt-5 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Reporting basis audit details</summary>
        <dl className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <dt className="text-xs text-muted">Framework</dt>
            <dd className="mt-1 font-mono text-xs">{policy.framework_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Matrix Version</dt>
            <dd className="mt-1 font-semibold">{policy.matrix_version}</dd>
          </div>
          <div className="md:col-span-2">
            <dt className="text-xs text-muted">Framework Policy Result</dt>
            <dd className="mt-1 break-words font-mono text-xs">{policy.result_id}</dd>
          </div>
        </dl>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {policy.decisions.map((decision) => (
            <article
              key={`audit:${decision.domain}:${decision.line_mappings.balance_sheet ?? decision.presentation}`}
              className="rounded border border-[var(--border)] p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{decision.domain}</p>
                  <p className="mt-1 text-xs font-mono text-muted">{decision.review_state}</p>
                </div>
                <span className="badge badge-muted">{decision.provenance}</span>
              </div>
              <dl className="mt-3 space-y-1 text-xs">
                {Object.entries(decision.line_mappings).map(([section, line]) => (
                  <div key={`${decision.domain}:${section}`} className="flex justify-between gap-3">
                    <dt className="text-muted">{section}</dt>
                    <dd className="font-mono text-right">{line}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
          {gaps.map((gap) => (
            <article
              key={`audit:${gap.code}:${gap.fact_id}`}
              className="rounded border border-[var(--border)] p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{gap.code}</p>
                  <p className="mt-1 text-xs font-mono text-muted">{gap.fact_id}</p>
                </div>
                <span className="badge badge-muted">{gap.instrument_type}</span>
              </div>
              <p className="mt-3 text-sm text-muted">{gap.reason}</p>
            </article>
          ))}
        </div>
      </details>
    </section>
  );
}

export function PackageSectionCards({
  sections,
}: {
  sections: PersonalReportPackageSections;
}) {
  const balanceSheet = sections.balance_sheet;
  const incomeStatement = sections.income_statement;
  const cashFlow = sections.cash_flow;
  const incompleteOpeningCoverage = cashFlow.proof_reasons?.includes("opening_coverage_starts_after_period") ?? false;
  const investment = sections.investment_performance;
  return (
    <div className="grid lg:grid-cols-2 gap-4 mb-6">
      <section id={sectionAnchorId("balance_sheet")} className="card p-5">
        <h2 className="font-semibold">Balance Sheet</h2>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <PackageMetric label="Total Assets" value={balanceSheet.total_assets} currency={balanceSheet.currency} />
          <PackageMetric label="Total Liabilities" value={balanceSheet.total_liabilities} currency={balanceSheet.currency} />
          <PackageMetric label="Total Equity" value={balanceSheet.total_equity} currency={balanceSheet.currency} />
          <PackageMetric label="Net Income" value={balanceSheet.net_income} currency={balanceSheet.currency} />
        </dl>
      </section>
      <section id={sectionAnchorId("income_statement")} className="card p-5">
        <h2 className="font-semibold">Income Statement</h2>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <PackageMetric label="Income" value={incomeStatement.total_income} currency={incomeStatement.currency} />
          <PackageMetric label="Expenses" value={incomeStatement.total_expenses} currency={incomeStatement.currency} />
          <PackageMetric label="Net Income" value={incomeStatement.net_income} currency={incomeStatement.currency} />
        </dl>
      </section>
      <section id={sectionAnchorId("cash_flow")} className="card p-5">
        <h2 className="font-semibold">Cash Flow</h2>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <PackageMetric label="Operating" value={cashFlow.summary.operating_activities} currency={cashFlow.currency} />
          <PackageMetric label="Investing" value={cashFlow.summary.investing_activities} currency={cashFlow.currency} />
          <PackageMetric label="Financing" value={cashFlow.summary.financing_activities} currency={cashFlow.currency} />
          <PackageMetric label="Net Cash Flow" value={cashFlow.summary.net_cash_flow} currency={cashFlow.currency} />
          <PackageMetric label={incompleteOpeningCoverage ? "Known Beginning Cash" : "Beginning Cash"} value={cashFlow.summary.beginning_cash} currency={cashFlow.currency} />
          <PackageMetric label="Ending Cash" value={cashFlow.summary.ending_cash} currency={cashFlow.currency} />
          {cashFlow.cash_bridge?.opening_stock_adjustment && (
            <PackageMetric label="Opening balance adjustment" value={cashFlow.cash_bridge.opening_stock_adjustment} currency={cashFlow.currency} />
          )}
        </dl>
        {cashFlow.proof_reasons?.includes("opening_position_unproven") && (
          <p className="mt-3 text-sm text-[var(--warning)]">Opening balance evidence needs review. Cash flow is not yet verified.</p>
        )}
        {incompleteOpeningCoverage && (
          <p className="mt-3 text-sm text-[var(--warning)]">
            Records start after the selected period begins. Beginning cash is only the known amount; full-period cash flow is not yet verified.
          </p>
        )}
      </section>
      <section id={sectionAnchorId("investment_performance")} className="card p-5">
        <h2 className="font-semibold">Investment Performance</h2>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <PackageMetric label="Realized P&L" value={investment.realized_pnl} currency={investment.currency} />
          <PackageMetric label="Unrealized P&L" value={investment.unrealized_pnl} currency={investment.currency} />
          <PackageMetric label="Dividend Income" value={investment.dividend_income} currency={investment.currency} />
        </dl>
        <div className="mt-4 space-y-2">
          {investment.holdings.length ? investment.holdings.map((holding) => (
            <div key={holding.asset_identifier} className="flex justify-between gap-3 border-t border-[var(--border)] pt-2 text-sm">
              <span>{holding.asset_identifier}</span>
              <span className="font-medium">{formatScheduleCurrency(holding.market_value, holding.currency)}</span>
            </div>
          )) : <p className="text-sm text-muted">No investment holdings in this period.</p>}
        </div>
      </section>
    </div>
  );
}

function PackageMetric({ label, value, currency }: { label: string; value: string; currency: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 font-semibold">{formatScheduleCurrency(value, currency)}</dd>
    </div>
  );
}

export function PackageAnnualizedScheduleSection({
  schedule,
}: {
  schedule: AnnualizedIncomeScheduleResponse;
}) {
  return (
    <section id="package-annualized-income-detail" className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Annualized Income Schedule</h2>
        </div>
        <span className="badge badge-muted">
          {schedule.trailing_period_days} days
        </span>
      </div>
      <div className="mt-4 grid md:grid-cols-4 gap-3">
        <div>
          <p className="text-xs text-muted">Total</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_total,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Salary</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_salary,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Bonus</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_bonus,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Dividend</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_dividend,
              schedule.income.currency,
            )}
          </p>
        </div>
      </div>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        <div>
          <h3 className="text-sm font-semibold">Restricted Holdings</h3>
          <div className="mt-3 space-y-2">
            {schedule.restricted_holdings.map((holding) => (
              <div
                key={`${holding.compensation_type}:${holding.ticker}`}
                className="border border-[var(--border)] rounded p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{holding.ticker}</p>
                    <p className="text-xs text-muted">
                      {holding.compensation_type}
                    </p>
                  </div>
                  <p className="font-semibold">
                    {formatScheduleCurrency(
                      holding.fair_value,
                      holding.currency,
                    )}
                  </p>
                </div>
                <dl className="mt-3 space-y-1 text-xs">
                  {holding.vesting_schedule ? (
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted">Vesting</dt>
                      <dd>{holding.vesting_schedule}</dd>
                    </div>
                  ) : null}
                  {holding.unlock_date ? (
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted">Unlock</dt>
                      <dd>{holding.unlock_date}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Net Worth Treatment</h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Liquid Default</dt>
              <dd className="font-mono text-xs text-right">
                {schedule.net_worth_treatment.liquid_net_worth_default}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Restricted Basis</dt>
              <dd className="font-mono text-xs text-right">
                {schedule.net_worth_treatment.restricted_wealth_basis}
              </dd>
            </div>
          </dl>
          <ul className="mt-4 space-y-1 text-sm text-muted">
            {schedule.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function PackageNotesSection({
  notes,
}: {
  notes: PersonalReportPackageNotesResponse;
}) {
  return (
    <section id="package-notes-detail" className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{notes.label}</h2>
        </div>
        <span className="badge badge-muted">{notes.status}</span>
      </div>
      <p className="mt-4 text-sm text-muted">
        {notes.non_compliance_statement}
      </p>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        {notes.notes.map((note) => (
          <article
            key={note.note_id}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{note.label}</p>
                <p className="text-xs font-mono text-muted mt-1">
                  {note.note_id}
                </p>
              </div>
              <span className="badge badge-muted">{note.owner_epic}</span>
            </div>
            <p className="mt-3 text-sm text-muted">{note.disclosure}</p>
            <dl className="mt-3 space-y-1 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Basis</dt>
                <dd className="font-mono text-right">{note.basis}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Source</dt>
                <dd className="font-mono text-right">{note.source_state}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function PackageExportContractSection({
  contract,
  policy,
  evidenceReferences,
}: {
  contract: PersonalReportPackageContractResponse;
  policy: FrameworkPolicyResult;
  evidenceReferences: string[];
}) {
  const frameworkLabel = FRAMEWORK_LABELS[policy.framework_id] ?? policy.framework_id;

  return (
    <section id="package-export-contract" className="card p-5">
      <h2 className="font-semibold">Export Options</h2>
      <p className="mt-2 text-sm text-muted">
        Snapshot exports are built from the selected reporting basis and evidence references.
      </p>
      <dl className="mt-4 space-y-2 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Formats</dt>
          <dd className="font-medium">
            {contract.export_contract.formats.join(", ")}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Decimal Serialization</dt>
          <dd className="font-medium">
            {contract.period_semantics.decimal_serialization}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Reporting basis</dt>
          <dd className="font-medium">{frameworkLabel}</dd>
        </div>
      </dl>
      <details className="mt-4 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Export audit details</summary>
        <dl className="mt-3 space-y-2">
          <div className="flex justify-between gap-3">
            <dt className="text-muted">CSV Columns</dt>
            <dd className="font-mono text-xs text-right">
              {contract.export_contract.csv_columns.join(", ")}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Framework Policy Result</dt>
            <dd className="max-w-md break-words font-mono text-xs text-right">
              {policy.result_id}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Framework Policy Matrix Version</dt>
            <dd className="font-medium">{policy.matrix_version}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Evidence Bundle References</dt>
            <dd className="max-w-md break-words font-mono text-xs text-right">
              {evidenceReferences.join(", ") || "none"}
            </dd>
          </div>
        </dl>
      </details>
    </section>
  );
}

export function PackageSnapshotsCard({
  snapshots,
  snapshotError,
  canGenerate,
  generating,
  downloading,
  selectedSnapshotId,
  onGenerate,
  onOpen,
  onDownload,
}: {
  snapshots: PersonalReportPackageSnapshotSummary[];
  snapshotError: string | null;
  canGenerate: boolean;
  generating: boolean;
  downloading: string | null;
  selectedSnapshotId: string | null;
  onGenerate: () => void;
  onOpen: (snapshot: PersonalReportPackageSnapshotSummary) => void;
  onDownload: (
    snapshot: PersonalReportPackageSnapshotSummary,
    format: "json" | "csv",
  ) => void;
}) {
  return (
    <section className="card p-5 mb-6 print:hidden">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Saved Package Artifacts</h2>
          <p className="mt-1 text-sm text-muted">
            Generate an immutable package snapshot before downloading JSON or CSV.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onGenerate}
            disabled={!canGenerate}
            className="btn-primary inline-flex items-center gap-2 text-sm"
          >
            <Save className="h-4 w-4" aria-hidden="true" />
            {generating ? "Generating..." : "Generate Snapshot"}
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <Printer className="h-4 w-4" aria-hidden="true" />
            Print / Save as PDF
          </button>
        </div>
      </div>
      {snapshotError ? (
        <p className="mt-3 text-sm text-[var(--error)]">{snapshotError}</p>
      ) : null}
      <div className="mt-5">
        <h3 className="text-sm font-semibold">Recent Snapshots</h3>
        {snapshots.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Framework</th>
                  <th className="py-2 pr-4 font-medium">Period</th>
                  <th className="py-2 pr-4 font-medium">Created</th>
                  <th className="py-2 font-medium">Downloads</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot) => (
                  <tr
                    key={snapshot.id}
                    className={
                      snapshot.id === selectedSnapshotId
                        ? "border-t border-[var(--border)] bg-[var(--background-muted)]"
                        : "border-t border-[var(--border)]"
                    }
                  >
                    <td className="py-3 pr-4">
                      <span className="badge badge-muted">
                        {snapshot.status === "trusted"
                          ? "Trusted"
                          : snapshot.status === "legacy_unproven"
                            ? "Legacy unproven"
                            : "Draft"}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      {FRAMEWORK_LABELS[snapshot.framework_id] ?? snapshot.framework_id}
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs">
                      {snapshot.start_date} to {snapshot.end_date}
                    </td>
                    <td className="py-3 pr-4 text-muted">
                      {formatSnapshotTimestamp(snapshot.created_at)}
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => onOpen(snapshot)}
                          disabled={snapshot.status === "legacy_unproven"}
                          className="btn-secondary text-xs"
                        >
                          {snapshot.id === selectedSnapshotId ? "Open" : "Reopen"}
                        </button>
                        <button
                          type="button"
                          onClick={() => onDownload(snapshot, "json")}
                          disabled={downloading === `${snapshot.id}:json`}
                          className="btn-secondary inline-flex items-center gap-2 text-xs"
                          aria-label={snapshotDownloadLabel(snapshot, "JSON")}
                        >
                          <FileJson className="h-4 w-4" aria-hidden="true" />
                          JSON
                        </button>
                        <button
                          type="button"
                          onClick={() => onDownload(snapshot, "csv")}
                          disabled={downloading === `${snapshot.id}:csv`}
                          className="btn-secondary inline-flex items-center gap-2 text-xs"
                          aria-label={snapshotDownloadLabel(snapshot, "CSV")}
                        >
                          <Download className="h-4 w-4" aria-hidden="true" />
                          CSV
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">No saved package snapshots yet.</p>
        )}
      </div>
    </section>
  );
}

export function PackageTraceabilitySection({
  appendix,
  onTrace,
}: {
  appendix: PersonalReportPackageTraceabilityResponse;
  onTrace: (line: PersonalReportPackageTraceabilityLine) => void;
}) {
  const linesWithEvidence = appendix.lines.filter(
    (line) =>
      line.source_anchor.state === "available" ||
      line.ledger_anchor.state === "available",
  ).length;

  return (
    <section id="package-traceability-detail" className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Traceability Summary</h2>
        </div>
        <span className="badge badge-muted">
          {humanizeIdentifier(appendix.status)}
        </span>
      </div>
      <dl className="mt-5 grid gap-3 text-sm md:grid-cols-3">
        <div>
          <dt className="text-xs text-muted">Report lines with evidence</dt>
          <dd className="mt-1 font-semibold">{linesWithEvidence}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Completeness warnings</dt>
          <dd className="mt-1 font-semibold">{appendix.completeness_warnings.length}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Appendix status</dt>
          <dd className="mt-1 font-semibold">{humanizeIdentifier(appendix.status)}</dd>
        </div>
      </dl>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {appendix.lines.map((line) => (
          <article key={line.line_id} className="rounded border border-[var(--border)] p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{line.label}</p>
                <p className="mt-1 text-xs text-muted">{humanizeIdentifier(line.section_id)}</p>
              </div>
              <button
                type="button"
                className="btn-secondary inline-flex h-9 w-9 items-center justify-center p-0"
                aria-label={`Trace evidence for ${line.label}`}
                title="Trace evidence"
                onClick={() => onTrace(line)}
              >
                <Network aria-hidden="true" className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="badge badge-muted">
                Source {humanizeIdentifier(line.source_anchor.state).toLowerCase()}
              </span>
              <span className="badge badge-muted">
                Ledger {humanizeIdentifier(line.ledger_anchor.state).toLowerCase()}
              </span>
              <span className="badge badge-muted">
                {countLabel(line.anchor_count ?? 0, "evidence anchor")}
              </span>
            </div>
          </article>
        ))}
      </div>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        {appendix.completeness_warnings.map((warning) => (
          <article
            key={warning.code}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{warning.label}</p>
              </div>
              <span className="badge badge-muted">{humanizeIdentifier(warning.state)}</span>
            </div>
            {warning.remediation ? (
              <p className="mt-3 text-sm text-muted">{warning.remediation}</p>
            ) : null}
          </article>
        ))}
      </div>
      <details className="mt-5 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Traceability audit details</summary>
        <p className="mt-3 text-xs text-muted">{appendix.label}</p>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Line</th>
                <th className="py-2 pr-4 font-medium">Source</th>
                <th className="py-2 pr-4 font-medium">Ledger</th>
                <th className="py-2 font-medium">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {appendix.lines.map((line) => (
                <tr
                  key={line.line_id}
                  className="border-t border-[var(--border)] align-top"
                >
                  <td className="py-3 pr-4">
                    <p className="font-mono text-xs">{line.line_id}</p>
                    <p className="mt-1 text-xs text-muted">{line.label}</p>
                  </td>
                  <td className="py-3 pr-4">
                    <p className="font-mono text-xs">{line.source_state}</p>
                    {renderAnchorDetail(
                      (line.source_anchor.source_types ?? []).join(", ") ||
                        line.source_anchor.state,
                      line.source_anchor.identifiers,
                    )}
                  </td>
                  <td className="py-3 pr-4">
                    <p className="font-mono text-xs">
                      {line.ledger_anchor.state}
                    </p>
                    {renderAnchorDetail(
                      (line.ledger_anchor.entry_statuses ?? []).join(", ") ||
                        line.ledger_anchor.unavailable_reason ||
                        line.ledger_anchor.state,
                      line.ledger_anchor.identifiers,
                    )}
                  </td>
                  <td className="py-3">
                    <div className="flex flex-col gap-2">
                      <span className="font-mono text-xs text-muted">
                        {line.anchor_count ?? 0} anchors
                      </span>
                      {line.blocker_codes?.length ? (
                        <span className="font-mono text-xs text-muted">
                          {line.blocker_codes.join(", ")}
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {appendix.completeness_warnings.map((warning) => (
            <article
              key={`audit:${warning.code}`}
              className="rounded border border-[var(--border)] p-3"
            >
              <p className="font-medium">{warning.label}</p>
              <dl className="mt-2 space-y-1 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Code</dt>
                  <dd className="font-mono text-right">{warning.code}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">State</dt>
                  <dd className="font-mono text-right">{warning.state}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </details>
    </section>
  );
}

export function LineagePanelModal({
  panel,
  onClose,
}: {
  panel: LineagePanelState;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end bg-black/30 p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Evidence Lineage"
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded border border-[var(--border)] bg-[var(--background)] shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
          <div>
            <p className="text-xs font-mono text-muted">
              {panel.line.line_id}
            </p>
            <h2 className="mt-1 font-semibold">Evidence Lineage</h2>
          </div>
          <button
            type="button"
            className="btn-secondary inline-flex h-9 w-9 items-center justify-center p-0"
            aria-label="Close evidence lineage"
            onClick={onClose}
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-4">
          {panel.isLoading ? (
            <p className="text-sm text-muted">Loading evidence lineage...</p>
          ) : panel.error ? (
            <p className="text-sm text-[var(--error)]">
              {panel.error}
            </p>
          ) : panel.response ? (
            <div className="space-y-5">
              {panel.response.blockers.length ? (
                <div className="space-y-2">
                  {panel.response.blockers.map((blocker) => (
                    <div
                      key={blocker.code}
                      className="rounded border border-[var(--border)] p-3"
                    >
                      <p className="font-mono text-xs">{blocker.code}</p>
                      <p className="mt-1 text-sm text-muted">
                        {blocker.message}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}
              <div>
                <h3 className="text-sm font-semibold">Nodes</h3>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {panel.response.nodes.map((node) => {
                    const displayTitle = nodeDisplayTitle(node);
                    const sourceHref = nodeSourceHref(node);
                    return (
                      <article
                        key={node.id}
                        className="rounded border border-[var(--border)] p-3"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <p className="font-mono text-xs">
                            {node.node_kind}
                          </p>
                          <span className="badge badge-muted">
                            {node.entity_type}
                          </span>
                        </div>
                        {sourceHref && (
                          <div className="mt-1.5">
                            <Link
                              href={sourceHref}
                              className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)] hover:underline"
                            >
                              {displayTitle ? `${displayTitle} ↗` : "Open source ↗"}
                            </Link>
                          </div>
                        )}
                        <p className="mt-2 break-words font-mono text-[11px] text-muted">
                          {nodeLabel(node)}
                        </p>
                      </article>
                    );
                  })}
                </div>
              </div>
              <div>
                <h3 className="text-sm font-semibold">Edges</h3>
                <div className="mt-3 space-y-2">
                  {panel.response.edges.map((edge) => (
                    <article
                      key={edge.id}
                      className="rounded border border-[var(--border)] p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs">
                          {edge.relation}
                        </span>
                        <span className="badge badge-muted">
                          {edge.direction}
                        </span>
                        <span className="font-mono text-xs text-muted">
                          depth {edge.depth}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
