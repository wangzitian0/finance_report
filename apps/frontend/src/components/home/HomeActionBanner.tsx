"use client";

import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { nextActionLabel, nextActionSummary, workflowStateCopy } from "@/components/workflow/workflowFormat";
import { useAttentionQueue } from "@/hooks/useAttentionQueue";
import { isWorkflowStatusResponse, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import type { AttentionItem } from "@/lib/attention";
import { NEEDS_YOU_HREF, withAttentionSource } from "@/lib/attentionNavigation";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowStatusResponse } from "@/lib/types";

/**
 * The one action banner of Home (#2621 LC, #2548 P1, #2646).
 *
 * Home shows workflow items only when one needs the user. The banner shows the first item
 * of this list and nothing when no item applies:
 *  1. the confidence queue has items: the count and the first item, with a link to the
 *     Needs you tab of `/audit`,
 *  2. the workflow is blocked or needs an action: the next action of the workflow status,
 *  3. the workflow has no source yet: upload the first statement.
 * The queue comes first: a blocker of the report package names no item, and the items of the
 * queue often cause it (#2646). The sources come from the shared query cache (#2583 S4):
 * `/audit` and the reconciliation Workbench read the same keys.
 */

export interface HomeAction {
  title: string;
  summary: string;
  cta: string;
  href: string;
  /** The first item of the confidence queue. The banner names it and links to it. */
  firstItem?: { title: string; detail: string; href: string };
}

export function pickHomeAction(status: WorkflowStatusResponse | null, queue: readonly AttentionItem[]): HomeAction | null {
  if (queue.length > 0) {
    const [first] = queue;
    return {
      title: `${countLabel(queue.length, "item")} ${queue.length === 1 ? "needs" : "need"} you`,
      summary: "Start with the item that the system is least sure about.",
      cta: "Open Needs you",
      href: NEEDS_YOU_HREF,
      firstItem: { title: first.title, detail: first.detail, href: withAttentionSource(first.href) },
    };
  }
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
  return null;
}

export function HomeActionBanner() {
  const workflow = useWorkflowStatusQuery();
  const queue = useAttentionQueue();

  const status = isWorkflowStatusResponse(workflow.data) ? workflow.data : null;
  // The banner stays silent while the queue loads: a workflow banner must not show first and then
  // change to the queue (#2646). It is not critical on Home, so a failed source shows no error.
  if (queue.items === null) return null;
  const action = pickHomeAction(status, queue.items);
  if (!action) return null;

  return (
    <section aria-label="Needs attention" className="card flex flex-col gap-2 border-[var(--warning)]/50 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-start gap-2">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{action.title}</h2>
          {action.firstItem ? (
            <p className="text-xs text-muted">
              <span>First: </span>
              <Link href={action.firstItem.href} className="font-medium text-[var(--foreground)] hover:underline">
                {action.firstItem.title}
              </Link>
              <span>{` · ${action.firstItem.detail}`}</span>
            </p>
          ) : (
            <p className="text-xs text-muted">{action.summary}</p>
          )}
        </div>
      </div>
      <Link href={action.href} className="btn-primary inline-flex shrink-0 items-center gap-1 px-3 py-1.5 text-xs">
        {action.cta}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </section>
  );
}
