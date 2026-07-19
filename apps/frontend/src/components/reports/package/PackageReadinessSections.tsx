import Link from "next/link";

import type {
  FrameworkPolicyResult,
  PersonalReportPackageInputCoverage,
  PersonalReportPackageReadinessResponse,
  PersonalReportPackageTraceManifestEntry,
} from "@/lib/types";
import { humanizeIdentifier } from "@/lib/statusLabels";

import { FRAMEWORK_LABELS } from "./shared";

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
          <dt className="text-xs text-muted">Authority Decisions</dt>
          <dd className="mt-1 font-semibold">
            {readiness.input_coverage.manifest_decision_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Authoritative Inputs</dt>
          <dd className="mt-1 font-semibold">
            {readiness.input_coverage.authoritative_input_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Unproven Inputs</dt>
          <dd className="mt-1 font-semibold">
            {readiness.input_coverage.unproven_input_count}
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
                  {decision.review_state === "accepted" ? "Accepted" : humanizeIdentifier(decision.review_state)}
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
