"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { Badge, EmptyState, LoadingState, type BadgeVariant } from "@/components/ui";
import { InfoHint, type GlossaryTerm } from "@/components/ui/InfoHint";
import { useApiQuery } from "@/hooks/useApiQuery";
import { buildAttentionItems, type AttentionKind } from "@/lib/attention";
import { withAttentionSource } from "@/lib/attentionNavigation";
import { PROCESSING_PENDING_QUERY_KEY, RECONCILIATION_STATS_QUERY_KEY, SHARED_STALE_MS, STATEMENTS_LIST_QUERY_KEY } from "@/lib/sharedQueries";

const KIND_TERM: Partial<Record<AttentionKind, GlossaryTerm>> = { statement_review: "needs_review", reconciliation_review: "match_score" };
const confidenceVariant = (c: number): BadgeVariant => (c < 40 ? "error" : c < 70 ? "warning" : "info");

/**
 * The one queue of items the user must confirm. Each row has the lowest
 * confidence first and links in one step to the statement or the entries.
 */
export function NeedsConfirmationQueue() {
  const statements = useApiQuery(STATEMENTS_LIST_QUERY_KEY, "list_statements_statements_get", {}, { staleTime: SHARED_STALE_MS });
  const stats = useApiQuery(RECONCILIATION_STATS_QUERY_KEY, "reconciliation_stats_reconciliation_stats_get", {}, { staleTime: SHARED_STALE_MS });
  const processing = useApiQuery(PROCESSING_PENDING_QUERY_KEY, "list_processing_pending_accounts_processing_pending_get", {}, { staleTime: SHARED_STALE_MS });
  const sources = [statements, stats, processing];

  const failed = sources.find((s) => s.isError);
  const retrying = sources.some((s) => s.isError && s.isFetching);
  const error = failed && !retrying ? (failed.error?.message ?? "Failed to load items that need confirmation") : null;
  // Show the rows of every source that loaded, even when another source failed.
  const settled = sources.every((s) => s.isSuccess || s.isError);
  const items = useMemo(
    () => (settled ? buildAttentionItems({ statements: statements.data?.items ?? [], stats: stats.data ?? null, processing: processing.data?.items ?? [] }) : null),
    [settled, statements.data?.items, stats.data, processing.data?.items],
  );

  const fetchItems = () => { for (const s of sources) if (s.isError) void s.refetch(); };

  return (
    <section id="needs-confirmation" data-testid="needs-confirmation-queue" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">Needs Confirmation</h2>
        <p className="text-xs text-muted">The lowest-confidence items first — the few things the system could not settle on its own. Everything else is already handled automatically.</p>
      </div>
      {items === null && !error && <LoadingState label="Loading items that need confirmation" />}
      {error && <EmptyState role="alert" title="Couldn't load the items that need confirmation" description={error} action={<button onClick={fetchItems} className="btn-secondary text-sm">Retry</button>} />}
      {items !== null && !failed && items.length === 0 && <EmptyState title="All clear" description="Nothing needs your review right now — the system trusts the rest of your data." />}
      {items !== null && items.length > 0 && (
        <>
          <div className="card divide-y divide-[var(--border)]">
            {items.map((item) => (
              <Link key={item.id} href={withAttentionSource(item.href)} className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-[var(--background-muted)]/50">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium truncate">{item.title}</span>
                    {KIND_TERM[item.kind] && <InfoHint term={KIND_TERM[item.kind] as GlossaryTerm} label={item.detail} />}
                  </div>
                  <p className="text-xs text-muted mt-0.5">{item.detail}</p>
                  <p className="text-xs text-muted mt-1 max-w-prose">{item.reason}</p>
                </div>
                <div className="flex flex-shrink-0 items-center gap-3">
                  <Badge variant={confidenceVariant(item.confidence)}>{item.confidence}% confidence</Badge>
                  <ArrowRight className="h-4 w-4 text-muted" aria-hidden="true" />
                </div>
              </Link>
            ))}
          </div>
          <p className="inline-flex items-center gap-1.5 text-xs text-muted">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Sorted by confidence — clearing these drives your low-confidence data down.
          </p>
        </>
      )}
    </section>
  );
}
