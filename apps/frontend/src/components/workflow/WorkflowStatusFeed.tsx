"use client";

import Link from "next/link";
import { Inbox } from "lucide-react";

import { Badge, cx } from "@/components/ui";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowEventResponse, WorkflowStatusResponse } from "@/lib/types";

import { labelFromSnake, nextActionLabel, routineEvents, sentenceFromSnake } from "./workflowFormat";

/**
 * Dashboard-level workflow status card (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export interface WorkflowStatusFeedProps {
  status: WorkflowStatusResponse;
  events: WorkflowEventResponse[];
}

export function WorkflowStatusFeed({ status, events }: WorkflowStatusFeedProps) {
  const actionableEvents = events.filter(
    (event) => event.severity === "blocked" || event.severity === "action_required",
  );
  const routineCount = routineEvents(events).length;
  const primaryHref = status.next_action.href;
  const primaryLabel = nextActionLabel(status);
  const readinessLabel = `Report ${sentenceFromSnake(status.report_readiness.state)}`;

  if (status.primary_state === "empty" && events.length === 0) {
    return (
      <section className="card p-5" aria-label="Workflow status">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Workflow status</h2>
            <p className="mt-1 text-sm text-muted">No action required</p>
          </div>
          <Link href={primaryHref} className="btn-primary inline-flex justify-center text-sm">
            Upload statements
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section className="card p-5" aria-label="Workflow status">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">Workflow status</h2>
          <p className="mt-1 text-sm text-muted">{labelFromSnake(status.primary_state)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant={status.report_readiness.state === "blocked" ? "error" : "info"}>{readinessLabel}</Badge>
            {status.event_counts.action_required > 0 && (
              <Badge variant="warning">{countLabel(status.event_counts.action_required, "action")}</Badge>
            )}
            {status.event_counts.blocked > 0 && (
              <Badge variant="error">{countLabel(status.event_counts.blocked, "blocked", "blocked")}</Badge>
            )}
          </div>
        </div>
        <Link href={primaryHref} className="btn-secondary inline-flex justify-center text-sm">
          {primaryLabel}
        </Link>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="space-y-3">
          {actionableEvents.slice(0, 3).map((event) => (
            <article
              key={event.id}
              className={cx(
                "rounded-md border p-3 text-sm",
                event.severity === "blocked"
                  ? "border-status-error bg-status-error-muted"
                  : "border-status-warning bg-status-warning-muted",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-medium">{event.title}</h3>
                  <p className="mt-1 text-sm text-muted">{event.summary}</p>
                </div>
                <Link
                  href={event.action_href}
                  className="btn-secondary shrink-0 px-3 py-1.5 text-xs"
                  aria-label={`Open ${event.title}`}
                >
                  Open
                </Link>
              </div>
            </article>
          ))}
          {actionableEvents.length === 0 && (
            <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">No action required</div>
          )}
        </div>

        <div className="rounded-md border border-border bg-surface-muted p-3">
          <div className="flex items-center gap-2">
            <Inbox className="h-4 w-4 text-muted" aria-hidden="true" />
            <h3 className="text-sm font-semibold">Routine automation</h3>
          </div>
          <p className="mt-2 text-sm text-muted">{countLabel(routineCount, "routine event")}</p>
          {routineCount > 0 && <p className="mt-1 text-xs text-muted">Latest: {routineEvents(events)[0]?.title}</p>}
        </div>
      </div>
    </section>
  );
}
