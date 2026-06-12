"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { apiFetch } from "@/lib/api";
import {
  buildAttentionItems,
  type AttentionItem,
  type AttentionKind,
} from "@/lib/attention";
import type {
  BankStatementListResponse,
  ProcessingPendingListResponse,
  ReconciliationStatsResponse,
} from "@/lib/types";
import { Badge, EmptyState, LoadingState, PageHeader, type BadgeVariant } from "@/components/ui";
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
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAttention = useCallback(async () => {
    // Reset to the loading state so a refresh/retry never shows stale items or a
    // misleading "all clear" while the new data is in flight.
    setItems(null);
    setError(null);
    try {
      const [statements, stats, processing] = await Promise.all([
        apiFetch<BankStatementListResponse>("/api/statements"),
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
        apiFetch<ProcessingPendingListResponse>("/api/accounts/processing/pending"),
      ]);
      setItems(
        buildAttentionItems({
          statements: statements?.items ?? [],
          stats: stats ?? null,
          processing: processing?.items ?? [],
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load attention items");
      setItems([]);
    }
  }, []);

  useEffect(() => {
    fetchAttention();
  }, [fetchAttention]);

  return (
    <div className="p-6">
      <PageHeader
        title="Needs your attention"
        description="The lowest-confidence items first — the few things the system could not settle on its own. Everything else is already handled automatically."
      />

      {items === null && !error && <LoadingState label="Loading attention items" />}

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
              href={item.href}
              className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-[var(--background-muted)]/50"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{item.title}</span>
                  {KIND_TERM[item.kind] && (
                    <InfoHint term={KIND_TERM[item.kind] as GlossaryTerm} label={item.detail} />
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">{item.detail}</p>
              </div>
              <div className="flex flex-shrink-0 items-center gap-3">
                <Badge variant={confidenceVariant(item.confidence)}>{item.confidence}% confidence</Badge>
                <ArrowRight className="h-4 w-4 text-muted" aria-hidden="true" />
              </div>
            </Link>
          ))}
        </div>
      )}

      {items !== null && items.length > 0 && (
        <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Sorted by confidence — clearing these drives your low-confidence data down.
        </p>
      )}
    </div>
  );
}
