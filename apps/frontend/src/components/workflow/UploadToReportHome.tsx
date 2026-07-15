"use client";

import Link from "next/link";
import { ArrowRight, CircleCheck, FileCheck2, Inbox, Loader2, UploadCloud } from "lucide-react";

import { Badge } from "@/components/ui";
import { isWorkflowStatusResponse, useWorkflowEventsQuery, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { countLabel, readinessVariant } from "@/lib/statusLabels";

import { WorkflowEventGroup } from "./WorkflowEventCard";
import type { WorkflowStatusFeedProps } from "./WorkflowStatusFeed";
import {
  formatEventTime,
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
  const readinessLabel = `Report ${sentenceFromSnake(status.report_readiness.state)}`;
  const blockerLabel = countLabel(status.report_readiness.blocking_count, "blocker");
  const primaryIsUpload = status.next_action.type === "upload";
  const activeSession = status.active_session;
  const activeSessionEvents = activeSession
    ? events.filter((event) => !event.session_id || event.session_id === activeSession.id)
    : events;

  return (
    <section className="space-y-4" aria-label="Upload-to-report home">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
        <div className="card p-5">
          <p className="text-xs uppercase tracking-wide text-muted">Your statements</p>
          <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold">{activeSession?.title ?? "Upload to report"}</h1>
              <p className="mt-2 max-w-2xl text-sm text-muted">{workflowStateCopy(status)}</p>
              {primarySummary && <p className="mt-2 max-w-2xl text-sm font-medium">{primarySummary}</p>}
              <div className="mt-4 flex flex-wrap gap-2">
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
            </div>
            <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
              <Link href={status.next_action.href} className="btn-primary inline-flex items-center justify-center gap-2 text-sm">
                {primaryIsUpload ? (
                  <UploadCloud className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                )}
                {primaryLabel}
              </Link>
              <Link href="/notifications" className="btn-secondary inline-flex items-center justify-center gap-2 text-sm">
                <Inbox className="h-4 w-4" aria-hidden="true" />
                Session history
              </Link>
            </div>
          </div>
        </div>

        <Link href={status.report_readiness.href} className="card block p-5 transition-colors hover:border-accent" aria-label="Report readiness">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted">Report readiness</p>
              <h2 className="mt-2 text-lg font-semibold">{readinessLabel}</h2>
            </div>
            <FileCheck2 className="h-5 w-5 text-muted" aria-hidden="true" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge variant={readinessVariant(status.report_readiness.state)}>{readinessLabel}</Badge>
            <Badge variant={status.report_readiness.blocking_count > 0 ? "error" : "muted"}>{blockerLabel}</Badge>
          </div>
          <p className="mt-3 text-sm text-muted">Open the report readiness path for blockers, processing state, or generated output.</p>
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.45fr)]">
        <section className="card p-5" aria-label="Workflow status">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Workflow status</h2>
              <p className="mt-1 text-sm text-muted">Required actions and blockers stay visible before analytics.</p>
            </div>
            <Badge variant="muted">{events.length} recent</Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <WorkflowEventGroup title="Blocked" events={groupedEvents.blocked.slice(0, 2)} />
            <WorkflowEventGroup title="Action required" events={groupedEvents.actionRequired.slice(0, 2)} />
          </div>
          {groupedEvents.blocked.length === 0 && groupedEvents.actionRequired.length === 0 && (
            <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">No action required</div>
          )}
          {activeSessionEvents.length > 0 && (
            <div className="mt-4 rounded-md border border-border bg-surface-muted p-3">
              <h3 className="text-sm font-semibold">Recent session timeline</h3>
              <ol className="mt-3 space-y-2">
                {activeSessionEvents.slice(0, 3).map((event) => (
                  <li key={event.id} className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate">{event.title}</span>
                    <time className="shrink-0 text-xs text-muted" dateTime={event.occurred_at}>
                      {formatEventTime(event.occurred_at)}
                    </time>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        <section className="card p-5" aria-label="Routine automation">
          <div className="flex items-center gap-2">
            <CircleCheck className="h-4 w-4 text-muted" aria-hidden="true" />
            <h2 className="text-sm font-semibold">Routine automation</h2>
          </div>
          <p className="mt-3 text-sm text-muted">{countLabel(groupedEvents.routine.length, "routine event")}</p>
          {groupedEvents.routine.length > 0 && (
            <div className="mt-3 rounded-md border border-border bg-surface-muted p-3 text-sm">
              <p className="font-medium">{groupedEvents.routine[0].title}</p>
              <p className="mt-1 text-muted">{groupedEvents.routine[0].summary}</p>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

export function UploadToReportHomePanel() {
  const statusQuery = useWorkflowStatusQuery();
  const eventsQuery = useWorkflowEventsQuery(5, "home");
  const status = isWorkflowStatusResponse(statusQuery.data) ? statusQuery.data : null;
  const events = eventsQuery.data?.items ?? [];

  if (statusQuery.isLoading || eventsQuery.isLoading) {
    return (
      <section className="card p-5" aria-label="Upload-to-report home">
        <div className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading upload-to-report workflow...
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
