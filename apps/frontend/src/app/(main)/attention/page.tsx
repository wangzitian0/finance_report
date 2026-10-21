"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { useApiQuery } from "@/hooks/useApiQuery";
import {
  buildAttentionItems,
  type AttentionKind,
} from "@/lib/attention";
import { withAttentionSource } from "@/lib/attentionNavigation";
import {
  PROCESSING_PENDING_QUERY_KEY,
  RECONCILIATION_STATS_QUERY_KEY,
  SHARED_STALE_MS,
  STATEMENTS_LIST_QUERY_KEY,
} from "@/lib/sharedQueries";
import {
  Badge,
  EmptyState,
  LoadingState,
  PageHeader,
  type BadgeVariant,
} from "@/components/ui";
import { InfoHint, type GlossaryTerm } from "@/components/ui/InfoHint";

// Each attention kind borrows the closest plain-language glossary term so the
// jargon stays explained inline (EPIC-022 AC22.5.5 reuse).
const KIND_TERM: Partial<Record<AttentionKind, GlossaryTerm>> = {
  statement_review: "needs_review",
  reconciliation_review: "match_score",
};

function confidenceVariant(confidence: number): BadgeVariant {
  if (confidence < 40) return "error";
  if (confidence < 70) return "warning";
  return "info";
}

export default function AttentionPage() {
  // The three sources come from the shared query cache (#2583 S4): Home and the
  // reconciliation Workbench read the same keys, so a source loads once per stale time.
  const statements = useApiQuery(
    STATEMENTS_LIST_QUERY_KEY,
    "list_statements_statements_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );
  const stats = useApiQuery(
    RECONCILIATION_STATS_QUERY_KEY,
    "reconciliation_stats_reconciliation_stats_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );
  const processing = useApiQuery(
    PROCESSING_PENDING_QUERY_KEY,
    "list_processing_pending_accounts_processing_pending_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );
  const sources = [statements, stats, processing];

  const failed = sources.find((source) => source.isError);
  // A retry keeps the failed status until the refetch answers; show the loading state meanwhile
  // so a retry never shows the old error or a misleading "all clear".
  const retrying = sources.some((source) => source.isError && source.isFetching);
  const error =
    failed && !retrying
      ? (failed.error?.message ?? "Failed to load attention items")
      : null;

  const statementItems = statements.data?.items;
  const statsData = stats.data;
  const processingItems = processing.data?.items;
  const ready = sources.every((source) => source.isSuccess);
  const items = useMemo(
    () =>
      ready
        ? buildAttentionItems({
            statements: statementItems ?? [],
            stats: statsData ?? null,
            processing: processingItems ?? [],
          })
        : null,
    [ready, statementItems, statsData, processingItems],
  );

  const fetchAttention = () => {
    for (const source of sources) {
      if (source.isError) void source.refetch();
    }
  };

  return (
    <div className="p-6">
      <PageHeader
        title="Needs your attention"
        description="The lowest-confidence items first — the few things the system could not settle on its own. Everything else is already handled automatically."
      />

      {items === null && !error && (
        <LoadingState label="Loading attention items" />
      )}

      {error && (
        <EmptyState
          role="alert"
          title="Couldn't load your attention items"
          description={error}
          action={
            <button onClick={fetchAttention} className="btn-secondary text-sm">
              Retry
            </button>
          }
        />
      )}

      {items !== null && !error && items.length === 0 && (
        <EmptyState
          title="All clear"
          description="Nothing needs your review right now — the system trusts the rest of your data."
        />
      )}

      {items !== null && items.length > 0 && (
        <div className="card divide-y divide-[var(--border)]">
          {items.map((item) => (
            <Link
              key={item.id}
              href={withAttentionSource(item.href)}
              className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-[var(--background-muted)]/50"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{item.title}</span>
                  {KIND_TERM[item.kind] && (
                    <InfoHint
                      term={KIND_TERM[item.kind] as GlossaryTerm}
                      label={item.detail}
                    />
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">{item.detail}</p>
                {/* AC22.11.2 — explain why this was flagged, not just a score. */}
                <p className="text-xs text-muted mt-1 max-w-prose">
                  {item.reason}
                </p>
              </div>
              <div className="flex flex-shrink-0 items-center gap-3">
                <Badge variant={confidenceVariant(item.confidence)}>
                  {item.confidence}% confidence
                </Badge>
                <ArrowRight className="h-4 w-4 text-muted" aria-hidden="true" />
              </div>
            </Link>
          ))}
        </div>
      )}

      {items !== null && items.length > 0 && (
        <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Sorted by confidence — clearing these drives your low-confidence data
          down.
        </p>
      )}
    </div>
  );
}
