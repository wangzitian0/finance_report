import { useInfiniteQuery } from "@tanstack/react-query";

import {
  TRACEABILITY_ANCHORS,
  lineDetailsQueryOptions,
  manifestEntriesQueryOptions,
  policyDecisionsQueryOptions,
} from "@/lib/packageEvidence";
import { countLabel, humanizeIdentifier } from "@/lib/statusLabels";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageTraceabilityAnchorName,
  PersonalReportPackageTraceabilityDetail,
  PersonalReportPackageTraceabilityLineSummary,
} from "@/lib/types";

// The evidence lists of a package document load only after the user opens them (#2583 S8, S11).
// A preview carries their counts. These components mount when the user opens a list, so a
// closed list never issues a request.

const ANCHOR_LABELS: Record<PersonalReportPackageTraceabilityAnchorName, string> = {
  source_anchor: "Source",
  ledger_anchor: "Ledger",
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function detailText(value: PersonalReportPackageTraceabilityDetail[string]): string {
  return value === null || value === undefined ? "" : String(value);
}

function AnchorDetails({
  document,
  line,
  anchor,
}: {
  document: PersonalReportPackageDocument;
  line: PersonalReportPackageTraceabilityLineSummary;
  anchor: PersonalReportPackageTraceabilityAnchorName;
}) {
  const query = useInfiniteQuery(lineDetailsQueryOptions(document, line.line_id, anchor));
  const details = query.data?.pages.flatMap((page) => page.details ?? []) ?? [];
  const total = query.data?.pages[0]?.total ?? line[anchor].detail_count;
  const label = `${ANCHOR_LABELS[anchor]} evidence for ${line.label}`;

  return (
    <section aria-label={label} className="rounded border border-[var(--border)] p-3">
      <p className="text-xs font-medium">
        {`${ANCHOR_LABELS[anchor]} evidence: ${details.length} of ${countLabel(total, "detail")}`}
      </p>
      {query.isLoading ? (
        <p role="status" className="mt-2 text-xs text-muted">
          Loading evidence...
        </p>
      ) : query.error ? (
        <p className="mt-2 text-xs text-[var(--error)]">
          {errorText(query.error, "Failed to load evidence.")}
        </p>
      ) : (
        <ul className="mt-2 max-h-72 space-y-2 overflow-y-auto pr-1">
          {details.map((detail) => (
            <li key={detailText(detail.identifier)} className="text-xs">
              <p className="break-all font-mono">{detailText(detail.identifier)}</p>
              <p className="text-muted">
                {[
                  humanizeIdentifier(detailText(detail.source_kind)),
                  detail.amount ? `${detailText(detail.amount)} ${detailText(detail.currency)}` : "",
                  detail.review_state ? humanizeIdentifier(detailText(detail.review_state)) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      )}
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary mt-2 text-xs"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : `Load more ${ANCHOR_LABELS[anchor].toLowerCase()} evidence`}
        </button>
      ) : null}
    </section>
  );
}

/** The details of one traceability line. It mounts when the user opens the line. */
export function TraceabilityLineEvidence({
  document,
  line,
}: {
  document: PersonalReportPackageDocument;
  line: PersonalReportPackageTraceabilityLineSummary;
}) {
  const anchors = TRACEABILITY_ANCHORS.filter((anchor) => line[anchor].detail_count > 0);
  if (!anchors.length) {
    return <p className="mt-3 text-xs text-muted">This line has no evidence details.</p>;
  }
  return (
    <div className="mt-3 space-y-3">
      {anchors.map((anchor) => (
        <AnchorDetails key={anchor} document={document} line={line} anchor={anchor} />
      ))}
    </div>
  );
}

/** Every framework policy decision. It mounts when the user opens the reporting basis audit details. */
export function PolicyDecisions({ document }: { document: PersonalReportPackageDocument }) {
  const query = useInfiniteQuery(policyDecisionsQueryOptions(document));
  const decisions = query.data?.pages.flatMap((page) => page.decisions ?? []) ?? [];
  const total = query.data?.pages[0]?.total ?? document.framework_policy.decision_count;

  if (query.isLoading) {
    return (
      <p role="status" className="mt-4 text-xs text-muted">
        Loading policy decisions...
      </p>
    );
  }
  if (query.error) {
    return <p className="mt-4 text-xs text-[var(--error)]">{errorText(query.error, "Failed to load the policy decisions.")}</p>;
  }
  return (
    <section aria-label="Policy decisions" className="mt-4">
      <p className="text-xs font-medium">{`Policy decisions: ${decisions.length} of ${total}`}</p>
      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        {decisions.map((d, index) => (
          <article
            key={d.evidence_anchors?.[0]?.anchor_id ?? `${d.domain}:${index}`}
            className="rounded border border-[var(--border)] p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{d.domain}</p>
                <p className="mt-1 text-xs font-mono text-muted">{d.review_state}</p>
              </div>
              <span className="badge badge-muted">{d.provenance}</span>
            </div>
            <dl className="mt-3 space-y-1 text-xs">
              {Object.entries(d.line_mappings).map(([section, line]) => (
                <div key={`${d.domain}:${section}`} className="flex justify-between gap-3">
                  <dt className="text-muted">{section}</dt>
                  <dd className="font-mono text-right">{line}</dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary mt-3 text-xs"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : "Load more policy decisions"}
        </button>
      ) : null}
    </section>
  );
}

/** The input manifest entries. It mounts when the user opens the manifest audit details. */
export function ManifestEntries({ document }: { document: PersonalReportPackageDocument }) {
  const query = useInfiniteQuery(manifestEntriesQueryOptions(document));
  const entries = query.data?.pages.flatMap((page) => page.entries ?? []) ?? [];

  if (query.isLoading) {
    return (
      <p role="status" className="mt-3 text-xs text-muted">
        Loading authority manifest...
      </p>
    );
  }
  if (query.error) {
    return (
      <p className="mt-3 text-xs text-[var(--error)]">
        {errorText(query.error, "Failed to load the authority manifest.")}
      </p>
    );
  }
  return (
    <div className="mt-3 space-y-2 font-mono text-xs">
      {entries.length ? (
        entries.map((entry) => (
          <p key={entry.decision_id}>
            {entry.decision_id} {entry.target_kind}:{entry.target_id}@{entry.target_version}
          </p>
        ))
      ) : (
        <p>No authority decisions are pinned for this document.</p>
      )}
      {query.hasNextPage ? (
        <button
          type="button"
          className="btn-secondary font-sans"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading..." : "Load more decisions"}
        </button>
      ) : null}
    </div>
  );
}
