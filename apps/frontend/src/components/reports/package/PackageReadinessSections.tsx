import Link from "next/link";

import type {
  FrameworkPolicyResult,
  PersonalReportPackageReadinessResponse,
} from "@/lib/types";

import {
  countLabel,
  FRAMEWORK_LABELS,
  humanizeIdentifier,
  renderCsv,
  renderSourceClasses,
} from "./shared";

type SourceTrustSummary = NonNullable<
  PersonalReportPackageReadinessResponse["source_trust_summary"]
>;

export function PackageReadinessSection({
  readiness,
}: {
  readiness: PersonalReportPackageReadinessResponse;
}) {
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
          <dt className="text-xs text-muted">Statements</dt>
          <dd className="mt-1 font-semibold">
            {readiness.source_summary.statements ?? 0}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Journal Entries</dt>
          <dd className="mt-1 font-semibold">
            {readiness.source_summary.posted_journal_entries ?? 0}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Manual Valuations</dt>
          <dd className="mt-1 font-semibold">
            {readiness.source_summary.manual_valuations ?? 0}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Blockers</dt>
          <dd className="mt-1 font-semibold">{readiness.blocking_count}</dd>
        </div>
      </dl>
      {readiness.blockers.length ? (
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {readiness.blockers.map((blocker) => (
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
        {readiness.blockers.length ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {readiness.blockers.map((blocker) => (
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

export function PackageSourceTrustSection({
  summary,
}: {
  summary: SourceTrustSummary;
}) {
  const coverageItems = [
    {
      label: "Imported evidence",
      values: summary.source_classes,
    },
    {
      label: "Verified by automated checks",
      values: summary.deterministic_pr_source_classes,
    },
    {
      label: "Verified with live extraction checks",
      values: summary.post_merge_llm_ocr_source_classes,
    },
    {
      label: "Manual evidence",
      values: summary.manual_trusted_source_classes,
    },
    {
      label: "Missing or unsupported evidence",
      values: summary.gap_source_classes,
    },
  ];

  return (
    <section id="package-source-trust" className="card p-5 mb-6" aria-label="Source trust summary">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Evidence Coverage</h2>
        </div>
        <span className="badge badge-muted">
          {countLabel(summary.source_classes.length, "evidence class", "evidence classes")}
        </span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        {coverageItems.map((item) => (
          <div key={item.label} className="rounded border border-[var(--border)] p-3">
            <dt className="text-xs text-muted">{item.label}</dt>
            <dd className="mt-1 font-medium">{renderSourceClasses(item.values)}</dd>
          </div>
        ))}
      </dl>
      <details className="mt-4 rounded border border-[var(--border)] p-3 text-sm print:hidden">
        <summary className="cursor-pointer font-medium">Evidence audit details</summary>
        <dl className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <dt className="text-xs text-muted">Source classes</dt>
            <dd className="mt-1 font-mono text-xs">{renderCsv(summary.source_classes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Deterministic PR</dt>
            <dd className="mt-1 font-mono text-xs">{renderCsv(summary.deterministic_pr_source_classes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Post-merge LLM/OCR</dt>
            <dd className="mt-1 font-mono text-xs">{renderCsv(summary.post_merge_llm_ocr_source_classes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Manual Trusted</dt>
            <dd className="mt-1 font-mono text-xs">{renderCsv(summary.manual_trusted_source_classes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Trust Gaps</dt>
            <dd className="mt-1 font-mono text-xs">{renderCsv(summary.gap_source_classes)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Blocker Codes</dt>
            <dd className="mt-1 font-mono text-xs">
              {summary.blocker_codes.join(", ") || "none"}
            </dd>
          </div>
        </dl>
      </details>
    </section>
  );
}

export function PackageFrameworkPolicySection({
  policy,
}: {
  policy: FrameworkPolicyResult;
}) {
  const frameworkLabel = FRAMEWORK_LABELS[policy.framework_id] ?? humanizeIdentifier(policy.framework_id);

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
            {policy.required_statements.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Decisions</dt>
          <dd className="mt-1 font-semibold">
            {policy.decisions.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Reporting gaps</dt>
          <dd className="mt-1 font-semibold">
            {policy.gaps.length}
          </dd>
        </div>
      </dl>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        {policy.decisions.map((decision) => (
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
                  Accepted
                </span>
              </div>
              <p className="mt-3 text-sm text-muted">{decision.presentation}</p>
            </article>
          ))}
        {policy.gaps.map((gap) => (
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
                <span className="badge badge-muted">{decision.confidence_tier}</span>
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
          {policy.gaps.map((gap) => (
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
