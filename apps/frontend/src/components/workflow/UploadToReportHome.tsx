"use client";

import Link from "next/link";
import { Badge } from "@/components/ui";
import { isWorkflowStatusResponse, useWorkflowEventsQuery, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowStatusFeedProps } from "./WorkflowStatusFeed";
import {
  humanizeWorkflowText, labelFromSnake, nextActionLabel, nextActionSummary,
  routineEvents as selectRoutineEvents, sentenceFromSnake, severityBadgeVariant, workflowStateCopy,
} from "./workflowFormat";

export function UploadToReportHome({ status, events }: WorkflowStatusFeedProps) {
  const blocked = events.filter((e) => e.severity === "blocked");
  const actions = events.filter((e) => e.severity === "action_required");
  const routine = selectRoutineEvents(events);
  const sessionTitle = status.active_session?.title ?? "Upload to report";
  const primaryCopy = workflowStateCopy(status);
  const summaryText = nextActionSummary(status);
  const readinessLabel = status.report_readiness.state === "none" ? "No reports generated yet" : `Report ${sentenceFromSnake(status.report_readiness.state)}`;
  const blockerLabel = countLabel(status.report_readiness.blocking_count, "blocker");

  return (
    <section aria-label="Upload-to-report home" className="card px-3 py-2.5">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <span className="sr-only">
            {sessionTitle !== "Upload to report" && <h2>Upload to report</h2>}
            <h2>Workflow status</h2>
          </span>
          <h1 className="text-sm font-semibold">{sessionTitle}</h1>
          <Badge variant={severityBadgeVariant(status.primary_state === "blocked" ? "blocked" : "info")}>{labelFromSnake(status.primary_state)}</Badge>
          <span className="text-xs text-muted">{primaryCopy}</span>
          {Boolean(summaryText && summaryText !== primaryCopy) && <span className="text-xs text-muted hidden sm:inline">{summaryText}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {blocked.length > 0 && <span>Blocked: {humanizeWorkflowText(blocked[0].title)}</span>}
          {actions.length > 0 && <span>Action required: {humanizeWorkflowText(actions[0].title)}</span>}
          {routine.length > 0 && (
            <span><strong className="font-medium">Routine automation</strong>: {routine.length} {routine.length === 1 ? "routine event" : "routine events"} ({humanizeWorkflowText(routine[0].title)})</span>
          )}
          {blocked.length === 0 && actions.length === 0 && routine.length === 0 && <span className="text-xs text-muted">No action required</span>}
          <Link href={status.report_readiness.href} aria-label="Report readiness" className="inline-flex items-center gap-1.5 rounded border border-[var(--border)] bg-[var(--background-muted)] px-2 py-1 text-xs hover:border-[var(--accent)]">
            <span className="font-medium">{readinessLabel}</span>
            <Badge variant={status.report_readiness.blocking_count > 0 ? "error" : "muted"}>{blockerLabel}</Badge>
          </Link>
          <Link href={status.next_action.href} className="btn-primary inline-flex items-center px-2.5 py-1 text-xs">{nextActionLabel(status)}</Link>
        </div>
      </div>
    </section>
  );
}

export function UploadToReportHomePanel() {
  const statusQuery = useWorkflowStatusQuery();
  const status = isWorkflowStatusResponse(statusQuery.data) ? statusQuery.data : null;
  const hasEvents = Boolean(status && (status.active_session != null || status.primary_state !== "empty" || status.event_counts.unread > 0 || status.event_counts.action_required > 0 || status.event_counts.blocked > 0));
  const eventsQuery = useWorkflowEventsQuery(5, "home", hasEvents);

  if (statusQuery.isLoading || (hasEvents && eventsQuery.isLoading)) {
    return (
      <section className="card px-3 py-2.5 animate-pulse" aria-label="Upload-to-report home" role="status" aria-busy="true">
        <div className="h-5 w-48 rounded bg-muted/20" />
      </section>
    );
  }
  if (statusQuery.isError || eventsQuery.isError || !status) {
    return (
      <section className="card px-3 py-2.5" aria-label="Upload-to-report home">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-sm font-semibold">Upload to report</h1>
            <p className="text-xs text-muted">Workflow status is unavailable. You can still upload files or open reports.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/upload" className="btn-primary px-2.5 py-1 text-xs">Upload statements</Link>
            <Link href="/reports" className="btn-secondary px-2.5 py-1 text-xs">Open reports</Link>
          </div>
        </div>
      </section>
    );
  }
  return <UploadToReportHome status={status} events={eventsQuery.data?.items ?? []} />;
}
