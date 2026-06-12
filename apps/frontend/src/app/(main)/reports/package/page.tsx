"use client";

import { Network, Printer, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ExportCsvButton } from "@/components/reports/ExportCsvButton";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import { formatDateInput } from "@/lib/date";
import {
  anchorFromIdentifiers,
  lineageUrl,
  nodeLabel,
  type LineageAnchor,
} from "@/lib/lineage";
import {
  reportPeriodStart,
  usePersonalReportPackage,
} from "@/hooks/usePersonalReportPackage";
import type {
  EvidenceLineageResponse,
  FrameworkPolicyResult,
  MoneyValue,
  PersonalReportPackageTraceabilityLine,
} from "@/lib/types";

const FRAMEWORK_LABELS: Record<string, string> = {
  personal_us_gaap_like: "US-like",
  personal_hkfrs_like: "HK-like",
};

function formatScheduleCurrency(
  value: MoneyValue,
  currency: string,
): string {
  return formatCurrencyLocale(value, currency, "en-US", {
    maximumFractionDigits: 0,
  }).replace(/\u00a0/g, " ");
}

function renderCsv(values?: string[]): string {
  return values && values.length ? values.join(", ") : "none";
}

function renderAnchorDetail(primary: string, identifiers?: string[]) {
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

function evidenceBundleReferences(
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

type LineagePanelState = {
  line: PersonalReportPackageTraceabilityLine;
  response: EvidenceLineageResponse | null;
  isLoading: boolean;
  error: string | null;
};

function lineageAnchorForLine(
  line: PersonalReportPackageTraceabilityLine,
): LineageAnchor | null {
  return anchorFromIdentifiers([
    ...(line.ledger_anchor.identifiers ?? []),
    ...(line.source_anchor.identifiers ?? []),
  ]);
}

export default function PersonalReportPackagePage() {
  const [selectedFrameworkId, setSelectedFrameworkId] = useState<string | null>(
    null,
  );
  const [reportDate, setReportDate] = useState(() => formatDateInput(new Date()));
  const [lineagePanel, setLineagePanel] = useState<LineagePanelState | null>(
    null,
  );
  const {
    contract,
    readiness,
    frameworkPolicy,
    annualizedSchedule,
    packageNotes,
    traceabilityAppendix,
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
    <section className="card p-5 mb-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-mono text-muted">framework_selection</p>
          <h2 className="font-semibold mt-1">Reporting Framework</h2>
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
              onChange={(event) => handleReportDateChange(event.target.value)}
              className="input w-auto"
              aria-label="Package report date"
            />
          </label>
          <div className="flex flex-wrap gap-2">{frameworkButtons}</div>
        </div>
      </div>
      {selectedFrameworkId ? (
        <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted">Selected Framework</dt>
            <dd className="mt-1 font-mono text-xs">{selectedFrameworkId}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Report Period</dt>
            <dd className="mt-1 font-mono text-xs">
              {reportPeriodStart(reportDate)} to {reportDate}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Policy Endpoint</dt>
            <dd className="mt-1 font-mono text-xs">
              {contract.framework_policy_endpoint}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Supported Frameworks</dt>
            <dd className="mt-1 font-mono text-xs">
              {contract.supported_frameworks.join(", ")}
            </dd>
          </div>
        </dl>
      ) : null}
    </section>
  );

  if (!selectedFrameworkId) {
    return (
      <div className="p-6">
        <div className="page-header">
          <h1 className="page-title">Personal Report Package</h1>
          <p className="page-description">{contract.package_id}</p>
        </div>
        {frameworkSelection}
      </div>
    );
  }

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
        {frameworkSelection}
        <div className="p-6 text-muted">Loading framework package...</div>
      </div>
    );
  }

  const evidenceReferences = evidenceBundleReferences(frameworkPolicy);
  const exportParams = new URLSearchParams({
    report_type: "package",
    format: "csv",
    framework_id: selectedFrameworkId,
    start_date: reportPeriodStart(reportDate),
    end_date: reportDate,
    as_of_date: reportDate,
  });
  const exportPath = `/api/reports/export?${exportParams.toString()}`;

  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">Personal Report Package</h1>
        <p className="page-description">{contract.package_id}</p>
      </div>

      {frameworkSelection}

      <section className="card p-5 mb-6 print:hidden">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-semibold">Export</h2>
            <p className="mt-1 text-sm text-muted">
              Save a readable copy of this package — pinned to the selected framework and report date.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => window.print()}
              className="btn-secondary inline-flex items-center gap-2 text-sm"
            >
              <Printer className="h-4 w-4" aria-hidden="true" />
              Print / Save as PDF
            </button>
            <ExportCsvButton path={exportPath} />
          </div>
        </div>
      </section>

      <section className="card p-5 mb-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-mono text-muted">report_readiness</p>
            <h2 className="font-semibold mt-1">Report Readiness</h2>
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

      {readiness.source_trust_summary ? (
        <section className="card p-5 mb-6" aria-label="Source trust summary">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-mono text-muted">
                source_trust_summary
              </p>
              <h2 className="font-semibold mt-1">Source Trust</h2>
            </div>
            <span className="badge badge-muted">
              {readiness.source_trust_summary.source_classes.length} classes
            </span>
          </div>
          <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Deterministic PR</dt>
              <dd className="mt-1 font-mono text-xs">
                {renderCsv(
                  readiness.source_trust_summary
                    .deterministic_pr_source_classes,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Post-merge LLM/OCR</dt>
              <dd className="mt-1 font-mono text-xs">
                {renderCsv(
                  readiness.source_trust_summary
                    .post_merge_llm_ocr_source_classes,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Manual Trusted</dt>
              <dd className="mt-1 font-mono text-xs">
                {renderCsv(
                  readiness.source_trust_summary.manual_trusted_source_classes,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Trust Gaps</dt>
              <dd className="mt-1 font-mono text-xs">
                {renderCsv(readiness.source_trust_summary.gap_source_classes)}
              </dd>
            </div>
          </dl>
          {readiness.source_trust_summary.blocker_codes.length ? (
            <div className="mt-4">
              <p className="text-xs text-muted">Blocker Codes</p>
              <p className="mt-1 font-mono text-xs">
                {readiness.source_trust_summary.blocker_codes.join(", ")}
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="card p-5 mb-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-mono text-muted">
              framework_policy_result
            </p>
            <h2 className="font-semibold mt-1">Framework Policy</h2>
            <p className="mt-2 max-w-3xl break-words font-mono text-xs text-muted">
              {frameworkPolicy.result_id}
            </p>
          </div>
          <span className="badge badge-muted">
            {frameworkPolicy.framework_id}
          </span>
        </div>
        <dl className="mt-5 grid md:grid-cols-4 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted">Framework</dt>
            <dd className="mt-1 font-mono text-xs">
              {frameworkPolicy.framework_id}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Matrix Version</dt>
            <dd className="mt-1 font-semibold">
              {frameworkPolicy.matrix_version}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Decisions</dt>
            <dd className="mt-1 font-semibold">
              {frameworkPolicy.decisions.length}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Gaps</dt>
            <dd className="mt-1 font-semibold">
              {frameworkPolicy.gaps.length}
            </dd>
          </div>
        </dl>
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {frameworkPolicy.decisions.map((decision) => (
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
          {frameworkPolicy.gaps.map((gap) => (
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

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        {contract.sections.map((section) => (
          <section key={section.section_id} className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-mono text-muted">
                  {section.section_id}
                </p>
                <h2 className="font-semibold mt-1">{section.label}</h2>
              </div>
              <span className="badge badge-muted">{section.status}</span>
            </div>
            <dl className="mt-4 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Owner</dt>
                <dd className="font-medium">{section.owner_epic}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Endpoint</dt>
                <dd className="font-mono text-xs text-right">
                  {section.source_endpoint}
                </dd>
              </div>
              {section.blocking_issue ? (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Follow-up</dt>
                  <dd className="font-medium">{section.blocking_issue}</dd>
                </div>
              ) : null}
            </dl>
          </section>
        ))}
      </div>

      <section className="card p-5 mb-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-mono text-muted">
              {annualizedSchedule.section_id}
            </p>
            <h2 className="font-semibold mt-1">Annualized Income Schedule</h2>
          </div>
          <span className="badge badge-muted">
            {annualizedSchedule.trailing_period_days} days
          </span>
        </div>
        <div className="mt-4 grid md:grid-cols-4 gap-3">
          <div>
            <p className="text-xs text-muted">Total</p>
            <p className="mt-1 font-semibold">
              {formatScheduleCurrency(
                annualizedSchedule.income.annualized_total,
                annualizedSchedule.income.currency,
              )}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Salary</p>
            <p className="mt-1 font-semibold">
              {formatScheduleCurrency(
                annualizedSchedule.income.annualized_salary,
                annualizedSchedule.income.currency,
              )}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Bonus</p>
            <p className="mt-1 font-semibold">
              {formatScheduleCurrency(
                annualizedSchedule.income.annualized_bonus,
                annualizedSchedule.income.currency,
              )}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted">Dividend</p>
            <p className="mt-1 font-semibold">
              {formatScheduleCurrency(
                annualizedSchedule.income.annualized_dividend,
                annualizedSchedule.income.currency,
              )}
            </p>
          </div>
        </div>
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          <div>
            <h3 className="text-sm font-semibold">Restricted Holdings</h3>
            <div className="mt-3 space-y-2">
              {annualizedSchedule.restricted_holdings.map((holding) => (
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
                  {
                    annualizedSchedule.net_worth_treatment
                      .liquid_net_worth_default
                  }
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Restricted Basis</dt>
                <dd className="font-mono text-xs text-right">
                  {
                    annualizedSchedule.net_worth_treatment
                      .restricted_wealth_basis
                  }
                </dd>
              </div>
            </dl>
            <ul className="mt-4 space-y-1 text-sm text-muted">
              {annualizedSchedule.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="card p-5 mb-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-mono text-muted">
              {packageNotes.section_id}
            </p>
            <h2 className="font-semibold mt-1">{packageNotes.label}</h2>
          </div>
          <span className="badge badge-muted">{packageNotes.status}</span>
        </div>
        <p className="mt-4 text-sm text-muted">
          {packageNotes.non_compliance_statement}
        </p>
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {packageNotes.notes.map((note) => (
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

      <section className="card p-5 mb-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-mono text-muted">
              {traceabilityAppendix.section_id}
            </p>
            <h2 className="font-semibold mt-1">{traceabilityAppendix.label}</h2>
          </div>
          <span className="badge badge-muted">
            {traceabilityAppendix.status}
          </span>
        </div>
        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Line</th>
                <th className="py-2 pr-4 font-medium">Source</th>
                <th className="py-2 pr-4 font-medium">Ledger</th>
                <th className="py-2 pr-4 font-medium">Review</th>
                <th className="py-2 font-medium">Confidence</th>
                <th className="py-2 pl-4 font-medium">Lineage</th>
              </tr>
            </thead>
            <tbody>
              {traceabilityAppendix.lines.map((line) => (
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
                  <td className="py-3 pr-4 font-mono text-xs">
                    {line.review_state}
                  </td>
                  <td className="py-3">
                    <div className="flex flex-col gap-2">
                      <span className="badge badge-muted">
                        {line.confidence_tier}
                      </span>
                      <span className="font-mono text-xs text-muted">
                        {line.proof_level ?? "unclassified"}
                      </span>
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
                  <td className="py-3 pl-4">
                    <button
                      type="button"
                      className="btn-secondary inline-flex h-9 w-9 items-center justify-center p-0"
                      aria-label={`Trace lineage for ${line.line_id}`}
                      title="Trace lineage"
                      onClick={() => void openLineagePanel(line)}
                    >
                      <Network aria-hidden="true" className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-5 grid lg:grid-cols-2 gap-4">
          {traceabilityAppendix.completeness_warnings.map((warning) => (
            <article
              key={warning.code}
              className="border border-[var(--border)] rounded p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{warning.label}</p>
                  <p className="text-xs font-mono text-muted mt-1">
                    {warning.code}
                  </p>
                </div>
                <span className="badge badge-muted">{warning.state}</span>
              </div>
              {warning.remediation ? (
                <p className="mt-3 text-sm text-muted">{warning.remediation}</p>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold">Export Contract</h2>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Formats</dt>
            <dd className="font-medium">
              {contract.export_contract.formats.join(", ")}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">CSV Columns</dt>
            <dd className="font-mono text-xs text-right">
              {contract.export_contract.csv_columns.join(", ")}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Decimal Serialization</dt>
            <dd className="font-medium">
              {contract.period_semantics.decimal_serialization}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Framework Policy Result</dt>
            <dd className="max-w-md break-words font-mono text-xs text-right">
              {frameworkPolicy.result_id}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Framework Policy Matrix Version</dt>
            <dd className="font-medium">{frameworkPolicy.matrix_version}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Evidence Bundle References</dt>
            <dd className="max-w-md break-words font-mono text-xs text-right">
              {evidenceReferences.join(", ") || "none"}
            </dd>
          </div>
        </dl>
      </section>
      {lineagePanel ? (
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
                  {lineagePanel.line.line_id}
                </p>
                <h2 className="mt-1 font-semibold">Evidence Lineage</h2>
              </div>
              <button
                type="button"
                className="btn-secondary inline-flex h-9 w-9 items-center justify-center p-0"
                aria-label="Close evidence lineage"
                onClick={() => setLineagePanel(null)}
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </div>
            <div className="overflow-y-auto p-4">
              {lineagePanel.isLoading ? (
                <p className="text-sm text-muted">Loading evidence lineage...</p>
              ) : lineagePanel.error ? (
                <p className="text-sm text-[var(--error)]">
                  {lineagePanel.error}
                </p>
              ) : lineagePanel.response ? (
                <div className="space-y-5">
                  {lineagePanel.response.blockers.length ? (
                    <div className="space-y-2">
                      {lineagePanel.response.blockers.map((blocker) => (
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
                      {lineagePanel.response.nodes.map((node) => (
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
                          <p className="mt-2 break-words font-mono text-[11px] text-muted">
                            {nodeLabel(node)}
                          </p>
                        </article>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">Edges</h3>
                    <div className="mt-3 space-y-2">
                      {lineagePanel.response.edges.map((edge) => (
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
      ) : null}
    </div>
  );
}
