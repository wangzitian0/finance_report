"use client";

import Link from "next/link";
import { ArrowRight, CircleCheck, FileCheck2, Inbox, UploadCloud } from "lucide-react";

import { Badge } from "@/components/ui";
import { isWorkflowStatusResponse, useWorkflowEventsQuery, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { countLabel } from "@/lib/statusLabels";

import { WorkflowEventGroup } from "./WorkflowEventCard";
import type { WorkflowStatusFeedProps } from "./WorkflowStatusFeed";
import {
  formatEventTime,
  humanizeWorkflowText,
  labelFromSnake,
  nextActionLabel,
  nextActionSummary,
  routineEvents,
  sentenceFromSnake,
  severityBadgeVariant,
  workflowStateCopy,
} from "./workflowFormat";

/**
 * The upload-to-report home dashboard panel (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export function UploadToReportHome({ status, events }: WorkflowStatusFeedProps) {
  const groupedEvents = {
    blocked: events.filter((event) => event.severity === "blocked"),
    actionRequired: events.filter((event) => event.severity === "action_required"),
    routine: routineEvents(events),
  };
  const primaryLabel = nextActionLabel(status);
  const primarySummary = nextActionSummary(status);
  const readinessLabel =
    status.report_readiness.state === "none"
      ? "No reports generated yet"
      : `Report ${sentenceFromSnake(status.report_readiness.state)}`;
  const blockerLabel = countLabel(status.report_readiness.blocking_count, "blocker");
  const primaryIsUpload = status.next_action.type === "upload";
  const activeSession = status.active_session;
  const activeSessionEvents = activeSession
    ? events.filter((event) => !event.session_id || event.session_id === activeSession.id)
    : events;

  return (
    <section className="space-y-2" aria-label="Upload-to-report home">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1.35fr)_minmax(16rem,0.65fr)]">
        <div className="card p-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] uppercase tracking-wide text-muted">Your statements</span>
                <h1 className="text-base font-semibold">{activeSession?.title ?? "Upload to report"}</h1>
                <Badge variant={severityBadgeVariant(status.primary_state === "blocked" ? "blocked" : "info")}>
                  {labelFromSnake(status.primary_state)}
                </Badge>
                {activeSession && <Badge variant="muted">{countLabel(activeSession.source_count, "session event")}</Badge>}
                {status.event_counts.action_required > 0 && (
                  <Badge variant="warning">{countLabel(status.event_counts.action_required, "action")}</Badge>
                )}
                {status.event_counts.blocked > 0 && (
                  <Badge variant="error">{countLabel(status.event_counts.blocked, "blocked", "blocked")}</Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-muted">{workflowStateCopy(status)}</p>
              {primarySummary && <p className="mt-0.5 text-xs font-medium">{primarySummary}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <Link href={status.next_action.href} className="btn-primary inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs">
                {primaryIsUpload ? (
                  <UploadCloud className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {primaryLabel}
              </Link>
              <Link href="/notifications" className="btn-secondary inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs">
                <Inbox className="h-3.5 w-3.5" aria-hidden="true" />
                Session history
              </Link>
            </div>
          </div>
        </div>

        <Link href={status.report_readiness.href} className="card flex items-center justify-between gap-3 p-3 transition-colors hover:border-accent" aria-label="Report readiness">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted">Report readiness</p>
            <h2 className="mt-0.5 text-sm font-semibold">{readinessLabel}</h2>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={status.report_readiness.blocking_count > 0 ? "error" : "muted"}>{blockerLabel}</Badge>
            <FileCheck2 className="h-4 w-4 text-muted" aria-hidden="true" />
          </div>
        </Link>
      </div>

      <div className={`grid gap-2 ${groupedEvents.routine.length > 0 ? "lg:grid-cols-[minmax(0,1fr)_minmax(14rem,0.45fr)]" : ""}`}>
        <section className="card p-3" aria-label="Workflow status">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Workflow status</h2>
            <Badge variant="muted">{events.length} recent</Badge>
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            <WorkflowEventGroup title="Blocked" events={groupedEvents.blocked.slice(0, 2)} />
            <WorkflowEventGroup title="Action required" events={groupedEvents.actionRequired.slice(0, 2)} />
          </div>
          {groupedEvents.blocked.length === 0 && groupedEvents.actionRequired.length === 0 && (
            <div className="rounded-md border border-border bg-surface-muted px-2.5 py-1.5 text-xs text-muted">No action required</div>
          )}
          {activeSessionEvents.length > 0 && (
            <div className="mt-2 rounded-md border border-border bg-surface-muted px-2.5 py-2">
              <h3 className="text-xs font-semibold">Recent session timeline</h3>
              <ol className="mt-1.5 flex flex-wrap gap-2 text-xs">
                {activeSessionEvents.slice(0, 3).map((event) => (
                  <li key={event.id} className="inline-flex items-center gap-1.5 rounded bg-[var(--background-card)] px-2 py-0.5 border border-[var(--border)]">
                    <span className="truncate max-w-[16rem]">{humanizeWorkflowText(event.title)}</span>
                    <time className="shrink-0 text-[11px] text-muted" dateTime={event.occurred_at}>
                      {formatEventTime(event.occurred_at)}
                    </time>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        {groupedEvents.routine.length > 0 && (
          <section className="card p-3" aria-label="Routine automation">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <CircleCheck className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
                <h2 className="text-xs font-semibold">Routine automation</h2>
              </div>
              <span className="text-[11px] text-muted">{countLabel(groupedEvents.routine.length, "routine event")}</span>
            </div>
            <div className="mt-2 rounded-md border border-border bg-surface-muted p-2 text-xs">
              <p className="font-medium">{humanizeWorkflowText(groupedEvents.routine[0].title)}</p>
              <p className="mt-0.5 text-muted">{humanizeWorkflowText(groupedEvents.routine[0].summary)}</p>
            </div>
          </section>
        )}
      </div>
    </section>
  );
}

export function UploadToReportHomePanel() {
  const statusQuery = useWorkflowStatusQuery();
  const status = isWorkflowStatusResponse(statusQuery.data) ? statusQuery.data : null;
  const hasWorkflowEvents = Boolean(
    status &&
      (status.active_session != null ||
        status.primary_state !== "empty" ||
        status.event_counts.unread > 0 ||
        status.event_counts.action_required > 0 ||
        status.event_counts.blocked > 0),
  );
  const eventsQuery = useWorkflowEventsQuery(5, "home", hasWorkflowEvents);
  const events = eventsQuery.data?.items ?? [];

  if (statusQuery.isLoading || (hasWorkflowEvents && eventsQuery.isLoading)) {
    return (
      <section className="space-y-4" aria-label="Upload-to-report home" role="status" aria-busy="true">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
          <div className="card p-5 space-y-4 animate-pulse">
            <div className="h-3 w-28 rounded bg-muted/20" />
            <div className="h-7 w-48 rounded bg-muted/20" />
            <div className="h-4 w-72 rounded bg-muted/20" />
            <div className="flex gap-2 pt-2">
              <div className="h-6 w-20 rounded bg-muted/20" />
              <div className="h-6 w-24 rounded bg-muted/20" />
            </div>
          </div>
          <div className="card p-5 space-y-4 animate-pulse">
            <div className="h-3 w-24 rounded bg-muted/20" />
            <div className="h-6 w-36 rounded bg-muted/20" />
            <div className="h-4 w-52 rounded bg-muted/20" />
          </div>
        </div>
      </section>
    );
  }

  if (statusQuery.isError || eventsQuery.isError || !status) {
    return (
      <section className="card p-5" aria-label="Upload-to-report home">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold">Upload to report</h1>
            <p className="mt-1 text-sm text-muted">Workflow status is unavailable. You can still upload files or open reports.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/upload" className="btn-primary text-sm">
              Upload statements
            </Link>
            <Link href="/reports" className="btn-secondary text-sm">
              Open reports
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return <UploadToReportHome status={status} events={events} />;
}
