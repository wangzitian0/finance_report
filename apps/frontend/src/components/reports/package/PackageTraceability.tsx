import { Network, X } from "lucide-react";

import { nodeLabel } from "@/lib/lineage";
import type {
  PersonalReportPackageTraceabilityLine,
  PersonalReportPackageTraceabilityResponse,
} from "@/lib/types";

import {
  countLabel,
  humanizeIdentifier,
  renderAnchorDetail,
  type LineagePanelState,
} from "./shared";

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
                <th className="py-2 pr-4 font-medium">Review</th>
                <th className="py-2 font-medium">Confidence</th>
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
                  {panel.response.nodes.map((node) => (
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
