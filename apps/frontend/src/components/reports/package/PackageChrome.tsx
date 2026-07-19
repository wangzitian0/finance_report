import { SkeletonBlock } from "@/components/ui";
import { reportPeriodStart } from "@/lib/reportPackage";
import type { PersonalReportPackageContractResponse } from "@/lib/types";

import { FRAMEWORK_LABELS, type PackageTocLink } from "./shared";

export function PackageCover({
  contract,
  reportDate,
  selectedFrameworkLabel,
}: {
  contract: PersonalReportPackageContractResponse;
  reportDate: string;
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
            <dt className="text-xs text-muted">Report Date</dt>
            <dd className="mt-1 font-mono text-xs">{reportDate}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Report Period</dt>
            <dd className="mt-1 font-mono text-xs">
              {reportPeriodStart(reportDate)} to {reportDate}
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
          ["2", "Confirm the date", "The report date pins period and point-in-time sections."],
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
  onSelectFramework,
  onReportDateChange,
}: {
  contract: PersonalReportPackageContractResponse;
  selectedFrameworkId: string | null;
  selectedFrameworkLabel: string | null;
  reportDate: string;
  onSelectFramework: (frameworkId: string) => void;
  onReportDateChange: (reportDate: string) => void;
}) {
  const frameworkButtons = contract.supported_frameworks.map((frameworkId) => {
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
            <span className="text-xs text-muted uppercase">Report date</span>
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
                {reportPeriodStart(reportDate)} to {reportDate}
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
                  {contract.supported_frameworks.join(", ")}
                </dd>
              </div>
            </dl>
          </details>
        </>
      ) : null}
    </section>
  );
}
