// EPIC-022 PR6 (#864): make confidence a first-class, navigable concept.
//
// Today "what needs my attention" is scattered across statement confidence
// scores, balance validation, reconciliation review, unmatched transactions,
// and stalled processing transfers — each with its own page and vocabulary.
// This module folds those existing read-API signals into one list ranked by
// confidence (lower = more uncertain = higher in the queue), which is exactly
// the low-confidence tail Axiom B says a human should look at.

import type {
  BankStatement,
  ProcessingPendingItem,
  ReconciliationStatsResponse,
} from "@/lib/types";

export type AttentionKind =
  | "statement_review"
  | "reconciliation_review"
  | "unmatched_transactions"
  | "processing_stalled";

export interface AttentionItem {
  /** Stable id so the list can dedupe/key without re-sync churn. */
  id: string;
  kind: AttentionKind;
  title: string;
  detail: string;
  /** 0–100; lower means the system is less sure and the user should look. */
  confidence: number;
  /** Deep-link to the surface where the user can act on this item. */
  href: string;
}

export interface AttentionSources {
  statements?: BankStatement[] | null;
  stats?: ReconciliationStatsResponse | null;
  processing?: ProcessingPendingItem[] | null;
}

/** A processing transfer is "stuck" once it has been in transit this long. */
export const PROCESSING_STALE_DAYS = 7;

/** Below this, an item is surfaced as low-confidence in the trust meter. */
export const LOW_CONFIDENCE_THRESHOLD = 50;

function clampConfidence(value: number): number {
  // `value || 0` folds NaN/undefined to 0 without a separate branch.
  return Math.max(0, Math.min(100, Math.round(value || 0)));
}

/**
 * Fold the available attention signals into a single list, sorted by ascending
 * confidence (the most uncertain items first). Ties break by id for a stable
 * order across re-syncs.
 */
export function buildAttentionItems(sources: AttentionSources): AttentionItem[] {
  const items: AttentionItem[] = [];

  // Stage 1 — parsed statements awaiting human review. A failed balance check
  // means lower confidence than the raw extraction score alone.
  for (const statement of sources.statements ?? []) {
    if (statement.status !== "parsed") continue;
    const score =
      typeof statement.confidence_score === "number" ? statement.confidence_score : 0;
    const balanceFailed = statement.balance_validated === false;
    items.push({
      id: `statement:${statement.id}`,
      kind: "statement_review",
      title: statement.original_filename,
      detail: balanceFailed ? "Balance needs review" : "Parsed — ready to review",
      confidence: clampConfidence(balanceFailed ? Math.min(score, 40) : score),
      href: `/statements/${statement.id}/review`,
    });
  }

  const stats = sources.stats;

  // Stage 2 — reconciliation matches awaiting review. Confidence tracks the
  // overall match rate for the batch they belong to. `match_rate` is already a
  // 0–100 percentage from the backend (matched / total * 100), not a fraction.
  if (stats && stats.pending_review > 0) {
    items.push({
      id: "reconciliation:pending",
      kind: "reconciliation_review",
      title: `${stats.pending_review} match${stats.pending_review > 1 ? "es" : ""} need review`,
      detail: "Reconciliation review",
      confidence: clampConfidence(stats.match_rate ?? 0),
      href: "/reconciliation/review-queue",
    });
  }

  // Unmatched transactions have no ledger match at all — the lowest confidence.
  if (stats && stats.unmatched_transactions > 0) {
    items.push({
      id: "reconciliation:unmatched",
      kind: "unmatched_transactions",
      title: `${stats.unmatched_transactions} unmatched transaction${
        stats.unmatched_transactions > 1 ? "s" : ""
      }`,
      detail: "No ledger match yet",
      confidence: 0,
      href: "/reconciliation/unmatched",
    });
  }

  // In-transit funds stuck in a processing account past the stale threshold.
  const stalled = (sources.processing ?? []).filter(
    (item) => item.days_outstanding >= PROCESSING_STALE_DAYS,
  );
  if (stalled.length > 0) {
    const oldest = stalled.reduce((max, item) => Math.max(max, item.days_outstanding), 0);
    items.push({
      id: "processing:stalled",
      kind: "processing_stalled",
      title: `${stalled.length} transfer${stalled.length > 1 ? "s" : ""} stuck in transit`,
      detail: `Oldest ${oldest} days outstanding`,
      confidence: 30,
      href: "/processing",
    });
  }

  return items.sort((a, b) => a.confidence - b.confidence || a.id.localeCompare(b.id));
}

export interface TrustSummary {
  /** Transactions the system already reconciled and trusts. */
  trusted: number;
  /** Open attention items the user should confirm. */
  needsConfirmation: number;
  /** Subset of attention items the system is least sure about. */
  lowConfidence: number;
}

/**
 * Summarise the trust posture for the Home trust meter. The north-star is to
 * drive `lowConfidence` down over time (Axiom B).
 */
export function summarizeTrust(
  items: AttentionItem[],
  stats?: ReconciliationStatsResponse | null,
): TrustSummary {
  return {
    trusted: stats?.matched_transactions ?? 0,
    needsConfirmation: items.length,
    lowConfidence: items.filter((item) => item.confidence < LOW_CONFIDENCE_THRESHOLD).length,
  };
}
