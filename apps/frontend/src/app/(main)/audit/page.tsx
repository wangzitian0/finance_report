"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { ChevronRight } from "lucide-react";

import {
  ActionChecklist,
  InvariantChecksGrid,
  TemporalTimelineGrid,
  TrustScoreHero,
} from "@/components/audit/TrustScoreHero";
import { AiSuggestionsQueue, useAiSuggestions } from "@/components/audit/AiSuggestionsQueue";
import { CorrectionLoopProof } from "@/components/audit/CorrectionLoopProof";
import { NeedsConfirmationQueue } from "@/components/audit/NeedsConfirmationQueue";
import { auditHubItems } from "@/components/navigation";
import { Stage2ReviewQueue } from "@/components/review/Stage2ReviewQueue";
import { LoadingState, PageHeader } from "@/components/ui";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useAttentionQueue } from "@/hooks/useAttentionQueue";
import { useDataQualityHealth } from "@/hooks/useDataQualityHealth";
import { isWorkflowStatusResponse, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { RECONCILIATION_STATS_QUERY_KEY, SHARED_STALE_MS } from "@/lib/sharedQueries";
import { countLabel } from "@/lib/statusLabels";

/**
 * `/audit`: three tabs, selected by `?tab=` (#2621 LE, #2646).
 *  - `needs-you`: the Needs Confirmation queue and the AI suggestions. `/attention`, `/confidence`
 *    and `/review/ai-suggestions` redirect here. A `run_id` adds the review of that run.
 *  - `health`: the trust score, the invariant checks, the 12-month timeline and the correction proof.
 *  - `books`: links to Reconciliation, Journal and Statements.
 * With no valid `tab`, the page opens on `needs-you` when an item needs the user or a `run_id` is
 * set, and on `health` when the queue and the suggestions are empty.
 */
const AUDIT_TABS = [
  { id: "needs-you", label: "Needs you" },
  { id: "health", label: "Health" },
  { id: "books", label: "Books" },
] as const;
type AuditTab = (typeof AUDIT_TABS)[number]["id"];

const BOOK_DESCRIPTIONS: Record<string, string> = {
  "/reconciliation": "How well your statements reconcile, and anything still unmatched.",
  "/journal": "The double-entry ledger behind every figure in your reports.",
  "/upload": "Uploaded bank, brokerage, and card statements with extraction status and transfers still in flight.",
};

function isAuditTab(value: string | null | undefined): value is AuditTab {
  return AUDIT_TABS.some((tab) => tab.id === value);
}

/** The `/audit` URL of a tab. It keeps `run_id` and `statement_id`, so a tab switch keeps the review scope. */
function auditTabHref(tab: AuditTab, searchParams: URLSearchParams): string {
  const params = new URLSearchParams();
  params.set("tab", tab);
  for (const key of ["run_id", "statement_id"]) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  return `/audit?${params.toString()}`;
}

export default function AuditPage() {
  const searchParams = useSearchParams();
  const tabParam = searchParams?.get("tab");
  const runId = searchParams?.get("run_id")?.trim() || null;
  const statementId = searchParams?.get("statement_id")?.trim() || undefined;
  const queue = useAttentionQueue();
  const suggestions = useAiSuggestions(statementId);

  // The badge counts the confidence queue, as the Home banner does: both read `useAttentionQueue`.
  // The AI suggestions are not added: their list also holds the pending matches that the queue
  // counts as one item. They still open this tab, by their `total` (the list is capped).
  const needsYouCount = queue.items?.length ?? 0;
  const suggestionTotal = suggestions.data?.total ?? suggestions.data?.items?.length ?? 0;
  const countsSettled = queue.items !== null && !suggestions.isPending;
  // A failed source opens `needs-you`: its error and its retry show there.
  const failed = queue.failed || suggestions.isError;
  const settledDefault: AuditTab | null =
    !countsSettled ? null : needsYouCount > 0 || suggestionTotal > 0 || failed ? "needs-you" : "health";
  // The first settled default stays: a later count change or a retry of a failed source does not move the tab.
  const [defaultTab, setDefaultTab] = useState<AuditTab | null>(null);
  if (defaultTab === null && settledDefault !== null) setDefaultTab(settledDefault);
  const activeTab: AuditTab | null = isAuditTab(tabParam) ? tabParam : runId ? "needs-you" : (defaultTab ?? settledDefault);
  const params = new URLSearchParams(searchParams?.toString() ?? "");

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <PageHeader title="Audit" description="The items that need you, the health of your books, and the ledgers behind them." />

      <nav role="tablist" aria-label="Audit tabs" className="flex gap-1 overflow-x-auto whitespace-nowrap border-b border-[var(--border)]">
        {AUDIT_TABS.map((tab) => (
          <Link
            key={tab.id}
            href={auditTabHref(tab.id, params)}
            scroll={false}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "border-[var(--accent)] text-[var(--foreground)]"
                : "border-transparent text-muted hover:text-[var(--foreground)]"
            }`}
          >
            {tab.label}
            {tab.id === "needs-you" && countsSettled && (
              <span data-testid="needs-you-count" className="badge badge-warning text-[10px]">
                {needsYouCount}
              </span>
            )}
          </Link>
        ))}
      </nav>

      <div role="tabpanel" aria-label={AUDIT_TABS.find((tab) => tab.id === activeTab)?.label ?? "Audit"}>
        {activeTab === null && <LoadingState label="Loading the items that need you" />}
        {activeTab === "needs-you" && (
          <div className="space-y-6">
            <NeedsConfirmationQueue />
            {runId && (
              <section aria-labelledby="run-review-heading" className="space-y-3">
                <h2 id="run-review-heading" className="text-sm font-semibold">Review this reconciliation run</h2>
                <Stage2ReviewQueue embedded runId={runId} />
              </section>
            )}
            <AiSuggestionsQueue />
          </div>
        )}
        {activeTab === "health" && <HealthTab />}
        {activeTab === "books" && <BooksTab />}
      </div>
    </div>
  );
}

/**
 * The hold of the audit-ready grade (#2646). A blocker of the workflow or an unmatched row is an
 * open item: the books are not ready while one exists. `reason` is null when no item holds the
 * grade. `settled` is false while a read loads: the Health tab shows no grade until it is true.
 * A failed read holds the grade, because it cannot show that no open item exists.
 */
function useAuditHold(): { settled: boolean; reason: string | null } {
  const workflow = useWorkflowStatusQuery();
  const stats = useApiQuery(RECONCILIATION_STATS_QUERY_KEY, "reconciliation_stats_reconciliation_stats_get", {}, { staleTime: SHARED_STALE_MS });
  const reasons: string[] = [];
  if (workflow.isError || stats.isError) {
    reasons.push("The open items could not be read.");
  }
  if (isWorkflowStatusResponse(workflow.data) && workflow.data.primary_state === "blocked") {
    reasons.push("A blocker holds your reports.");
  }
  const unmatched = stats.data?.unmatched_transactions ?? 0;
  if (unmatched > 0) {
    reasons.push(`${countLabel(unmatched, "transaction")} ${unmatched === 1 ? "has" : "have"} no ledger match.`);
  }
  return { settled: !workflow.isPending && !stats.isPending, reason: reasons.length > 0 ? reasons.join(" ") : null };
}

function HealthTab() {
  const { data, isLoading, isError, refetch, isFetching } = useDataQualityHealth();
  const hold = useAuditHold();
  const heldReason = hold.reason;

  return (
    <div className="space-y-8">
      {isLoading || !hold.settled ? (
        <div className="card space-y-4 p-8 text-center">
          <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--accent)]" />
          <p className="text-sm text-muted">Evaluating accounting invariants and temporal timeline...</p>
        </div>
      ) : isError || !data || typeof data.score !== "number" || !data.equation_invariant ? (
        <div className="card border-[var(--error)] p-6 text-center">
          <p className="text-sm font-medium text-[var(--error)]">Failed to evaluate data quality health.</p>
          <button type="button" onClick={() => refetch()} className="btn-primary mt-3 text-xs">
            Retry Evaluation
          </button>
        </div>
      ) : (
        <>
          <TrustScoreHero
            score={data.score}
            grade={data.grade}
            asOfDate={data.as_of_date}
            currency={data.currency}
            isRefreshing={isFetching}
            onRefresh={() => refetch()}
            heldReason={heldReason}
          />
          <ActionChecklist actionItems={data.action_items} heldReason={heldReason} />
          <InvariantChecksGrid
            equationInvariant={data.equation_invariant}
            temporalInvariant={data.temporal_continuity_invariant}
            reconciliationInvariant={data.reconciliation_purity_invariant}
            lineageInvariant={data.lineage_anchors_invariant}
          />
          <TemporalTimelineGrid timeline={data.timeline} />
        </>
      )}
      <CorrectionLoopProof />
    </div>
  );
}

function BooksTab() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {auditHubItems.map((item) => {
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className="card flex items-start gap-3 p-4 transition-colors hover:bg-[var(--background-muted)]"
          >
            <span className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-[var(--accent-muted)] text-[var(--accent)]">
              <Icon className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium text-sm">{item.label}</span>
                <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
              </span>
              <span className="mt-0.5 block text-xs text-muted">{BOOK_DESCRIPTIONS[item.href]}</span>
            </span>
          </Link>
        );
      })}
    </div>
  );
}
