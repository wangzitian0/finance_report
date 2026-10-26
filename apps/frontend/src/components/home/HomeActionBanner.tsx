"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { nextActionLabel, nextActionSummary, workflowStateCopy } from "@/components/workflow/workflowFormat";
import { useApiQuery } from "@/hooks/useApiQuery";
import { isWorkflowStatusResponse, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { buildAttentionItems, summarizeTrust } from "@/lib/attention";
import {
  PROCESSING_PENDING_QUERY_KEY,
  RECONCILIATION_STATS_QUERY_KEY,
  SHARED_STALE_MS,
  STATEMENTS_LIST_QUERY_KEY,
} from "@/lib/sharedQueries";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowStatusResponse } from "@/lib/types";

/**
 * The one action banner of Home (#2621 LC, #2548 P1).
 *
 * Home shows workflow items only when one needs the user. The banner shows the first item
 * of this list and nothing when no item applies:
 *  1. the workflow is blocked or needs an action: the next action of the workflow status,
 *  2. the workflow has no source yet: upload the first statement,
 *  3. the confidence-ranked queue has items: the count, with a link to `/audit`.
 * The sources come from the shared query cache (#2583 S4): `/audit` and the reconciliation
 * Workbench read the same keys.
 */

export interface HomeAction {
  title: string;
  summary: string;
  cta: string;
  href: string;
}

export function pickHomeAction(status: WorkflowStatusResponse | null, needsConfirmation: number): HomeAction | null {
  if (status?.primary_state === "blocked" || status?.primary_state === "needs_action") {
    return {
      title: status.primary_state === "blocked" ? "A blocker holds your reports" : "An item needs your review",
      summary: nextActionSummary(status) || workflowStateCopy(status),
      cta: nextActionLabel(status),
      href: status.next_action.href,
    };
  }
  if (status?.primary_state === "empty") {
    return {
      title: "Upload your first statement",
      summary: "The three statements fill in after you upload and approve a bank statement.",
      cta: "Upload statements",
      href: "/upload",
    };
  }
  if (needsConfirmation > 0) {
    return {
      title: `${countLabel(needsConfirmation, "item")} ${needsConfirmation === 1 ? "needs" : "need"} your confirmation`,
      summary: "Confirm the lowest-confidence items first so the statements stay accurate.",
      cta: "Open Needs Confirmation",
      href: "/audit",
    };
  }
  return null;
}

export function HomeActionBanner() {
  const workflow = useWorkflowStatusQuery();
  const statements = useApiQuery(STATEMENTS_LIST_QUERY_KEY, "list_statements_statements_get", {}, { staleTime: SHARED_STALE_MS });
  const stats = useApiQuery(RECONCILIATION_STATS_QUERY_KEY, "reconciliation_stats_reconciliation_stats_get", {}, { staleTime: SHARED_STALE_MS });
  const processing = useApiQuery(
    PROCESSING_PENDING_QUERY_KEY,
    "list_processing_pending_accounts_processing_pending_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );

  const status = isWorkflowStatusResponse(workflow.data) ? workflow.data : null;
  const trustReady = statements.isSuccess && stats.isSuccess && processing.isSuccess;
  const statementItems = statements.data?.items;
  const statsData = stats.data;
  const processingItems = processing.data?.items;
  const needsConfirmation = useMemo(() => {
    if (!trustReady) return 0;
    const items = buildAttentionItems({
      statements: statementItems ?? [],
      stats: statsData ?? null,
      processing: processingItems ?? [],
    });
    return summarizeTrust(items, statsData ?? null).needsConfirmation;
  }, [trustReady, statementItems, statsData, processingItems]);

  // The banner stays silent while its sources load and when they fail: it is not critical on Home.
  const action = pickHomeAction(status, needsConfirmation);
  if (!action) return null;

  return (
    <section aria-label="Needs attention" className="card flex flex-col gap-2 border-[var(--warning)]/50 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{action.title}</h2>
          <p className="text-xs text-muted">{action.summary}</p>
        </div>
      </div>
      <Link href={action.href} className="btn-primary inline-flex shrink-0 items-center gap-1 px-3 py-1.5 text-xs">
        {action.cta}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </section>
  );
}
