import Link from "next/link";

import type {
  FrameworkPolicyResult,
  PersonalReportPackageReadinessResponse,
} from "@/lib/types";

import { renderCsv } from "./shared";

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
                  <p className="text-xs font-mono text-muted mt-1">
                    {blocker.code}
                  </p>
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
    </section>
  );
}

export function PackageSourceTrustSection({
  summary,
}: {
  summary: SourceTrustSummary;
}) {
  return (
    <section id="package-source-trust" className="card p-5 mb-6" aria-label="Source trust summary">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Source Trust</h2>
        </div>
        <span className="badge badge-muted">
          {summary.source_classes.length} classes
        </span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <div>
          <dt className="text-xs text-muted">Deterministic PR</dt>
          <dd className="mt-1 font-mono text-xs">
            {renderCsv(summary.deterministic_pr_source_classes)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Post-merge LLM/OCR</dt>
          <dd className="mt-1 font-mono text-xs">
            {renderCsv(summary.post_merge_llm_ocr_source_classes)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Manual Trusted</dt>
          <dd className="mt-1 font-mono text-xs">
            {renderCsv(summary.manual_trusted_source_classes)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Trust Gaps</dt>
          <dd className="mt-1 font-mono text-xs">
            {renderCsv(summary.gap_source_classes)}
          </dd>
        </div>
      </dl>
      {summary.blocker_codes.length ? (
        <div className="mt-4">
          <p className="text-xs text-muted">Blocker Codes</p>
          <p className="mt-1 font-mono text-xs">
            {summary.blocker_codes.join(", ")}
          </p>
        </div>
      ) : null}
    </section>
  );
}

export function PackageFrameworkPolicySection({
  policy,
}: {
  policy: FrameworkPolicyResult;
}) {
  return (
    <section id="package-framework-policy" className="card p-5 mb-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Framework Policy</h2>
          <p className="mt-2 max-w-3xl break-words font-mono text-xs text-muted">
            {policy.result_id}
          </p>
        </div>
        <span className="badge badge-muted">
          {policy.framework_id}
        </span>
      </div>
      <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted">Framework</dt>
          <dd className="mt-1 font-mono text-xs">
            {policy.framework_id}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Matrix Version</dt>
          <dd className="mt-1 font-semibold">
            {policy.matrix_version}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Decisions</dt>
          <dd className="mt-1 font-semibold">
            {policy.decisions.length}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Gaps</dt>
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
                <p className="font-medium">{decision.domain}</p>
                <p className="mt-1 text-xs font-mono text-muted">
                  {decision.review_state}
                </p>
              </div>
              <span className="badge badge-muted">
                {decision.confidence_tier}
              </span>
            </div>
            <dl className="mt-3 space-y-1 text-xs">
              {Object.entries(decision.line_mappings).map(
                ([section, line]) => (
                  <div
                    key={`${decision.domain}:${section}`}
                    className="flex justify-between gap-3"
                  >
                    <dt className="text-muted">{section}</dt>
                    <dd className="font-mono text-right">{line}</dd>
                  </div>
                ),
              )}
            </dl>
          </article>
        ))}
        {policy.gaps.map((gap) => (
          <article
            key={`${gap.code}:${gap.fact_id}`}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{gap.code}</p>
                <p className="mt-1 text-xs font-mono text-muted">
                  {gap.fact_id}
                </p>
              </div>
              <span className="badge badge-muted">{gap.instrument_type}</span>
            </div>
            <p className="mt-3 text-sm text-muted">{gap.reason}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
