"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Bell, Check, ChevronRight, ExternalLink, Inbox, Loader2 } from "lucide-react";

import { Sheet } from "@/components/ui/Overlay";
import { Alert, Badge, EmptyState, cx } from "@/components/ui";
import { isWorkflowStatusResponse, useWorkflowEventsQuery, useWorkflowLifecycleMutation, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowEventResponse, WorkflowEventStatus, WorkflowSessionSummaryResponse, WorkflowStatusResponse } from "@/lib/types";
import {
  formatEventTime, groupEventsBySession, humanizeWorkflowText, labelFromSnake, nextActionLabel,
  routineEvents as selectRoutineEvents, sentenceFromSnake, severityBadgeVariant, severityIcon, workflowEventCardClass,
} from "./workflowFormat";

export type FlowStep = "upload" | "review" | "reports";
const STEPS: { key: FlowStep; label: string; href: string }[] = [
  { key: "upload", label: "Upload", href: "/upload" },
  { key: "review", label: "Review & approve", href: "/upload#statements" },
  { key: "reports", label: "Reports", href: "/reports" },
];
const NEXT_HINT: Record<FlowStep, string> = {
  upload: "Next: once we parse your statement, review and approve it.",
  review: "Next: approve to post entries — your reports update automatically.",
  reports: "You're all set. Open any amount to trace it back to its source.",
};

export function FlowStepBanner({ current }: { current: FlowStep }) {
  const currentIndex = STEPS.findIndex((s) => s.key === current);
  return (
    <nav aria-label="Upload to reports progress" className="card flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
      <ol className="flex flex-wrap items-center gap-1 text-sm">
        {STEPS.map((step, index) => {
          const isCurrent = step.key === current;
          const isDone = index < currentIndex;
          return (
            <li key={step.key} className="flex items-center gap-1">
              <Link href={step.href} aria-current={isCurrent ? "step" : undefined} className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 transition-colors ${isCurrent ? "bg-[var(--accent-muted)] font-semibold text-[var(--accent)]" : "text-muted hover:text-[var(--foreground)]"}`}>
                <span aria-hidden="true" className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${isCurrent ? "bg-[var(--accent)] text-white" : isDone ? "bg-[var(--success-muted)] text-[var(--success)]" : "bg-[var(--background-muted)] text-muted"}`}>
                  {isDone ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index + 1}
                </span>
                {step.label}
              </Link>
              {index < STEPS.length - 1 && <span aria-hidden="true" className="px-1 text-muted"><ChevronRight className="h-4 w-4" /></span>}
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-muted">{NEXT_HINT[current]}</p>
    </nav>
  );
}

export interface WorkflowStatusFeedProps {
  status: WorkflowStatusResponse;
  events: WorkflowEventResponse[];
}

export function WorkflowEventCard({ event, className = workflowEventCardClass(event), openLabel, showIcon = true, onStatusChange }: {
  event: WorkflowEventResponse; className?: string; openLabel?: string; showIcon?: boolean; onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}) {
  const Icon = severityIcon(event.severity);
  const displayTitle = humanizeWorkflowText(event.title);
  const displaySummary = humanizeWorkflowText(event.summary);
  return (
    <article className={`${className} !p-2.5`}>
      <div className="flex min-w-0 items-start gap-2">
        {showIcon && <Icon className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted" aria-hidden="true" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-1.5">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5"><h4 className="min-w-0 text-xs font-medium [overflow-wrap:anywhere]">{displayTitle}</h4><Badge variant={severityBadgeVariant(event.severity)}>{labelFromSnake(event.severity)}</Badge></div>
            <time className="text-[11px] text-muted" dateTime={event.occurred_at}>{formatEventTime(event.occurred_at)}</time>
          </div>
          <p className="mt-0.5 text-xs text-muted [overflow-wrap:anywhere]">{displaySummary}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Link href={event.action_href} className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-[11px]" aria-label={`Open ${displayTitle}`}><ExternalLink className="h-3 w-3" aria-hidden="true" />{openLabel ?? `Open ${displayTitle}`}</Link>
            {event.status === "unread" && onStatusChange && <button type="button" className="btn-ghost px-2 py-1 text-[11px]" onClick={() => onStatusChange(event.id, "read")}>Mark as read</button>}
            {event.status !== "archived" && onStatusChange && <button type="button" className="btn-ghost px-2 py-1 text-[11px]" onClick={() => onStatusChange(event.id, "archived")}>Archive</button>}
          </div>
        </div>
      </div>
    </article>
  );
}

export function WorkflowInbox({ events, sessions = [], onStatusChange }: {
  events: WorkflowEventResponse[]; sessions?: WorkflowSessionSummaryResponse[]; onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}) {
  if (events.length === 0) return <EmptyState title="No action required" description="Workflow events will appear here when review or blockers need attention." action={<Link href="/upload" className="btn-primary inline-flex">Upload statements</Link>} />;
  return (
    <div className="space-y-3">
      {groupEventsBySession(events, sessions).map(({ session, events: sessionEvents }) => (
        <details key={session.id} className="rounded-md border border-border bg-surface-card p-3" open={session.status === "active"}>
          <summary className="cursor-pointer list-none">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><h3 className="text-sm font-semibold [overflow-wrap:anywhere]">{humanizeWorkflowText(session.title)}</h3><p className="mt-1 text-xs text-muted [overflow-wrap:anywhere]">{humanizeWorkflowText(session.summary)}</p></div>
              <Badge variant={session.event_counts.blocked > 0 ? "error" : session.event_counts.action_required > 0 ? "warning" : "muted"}>{countLabel(sessionEvents.length, "event")}</Badge>
            </div>
            <p className="mt-2 text-xs text-muted">Latest: {session.last_event_at ? formatEventTime(session.last_event_at) : "No events yet"}</p>
          </summary>
          <ol className="mt-4 space-y-3" aria-label={`${session.title} timeline`}>
            {sessionEvents.map((event) => {
              const Icon = severityIcon(event.severity);
              return (
                <li key={event.id} className="flex gap-3">
                  <div className="mt-1 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-surface-muted"><Icon className="h-3.5 w-3.5 text-muted" aria-hidden="true" /></div>
                  <WorkflowEventCard event={event} className="min-w-0 flex-1 rounded-md border border-border bg-surface-muted p-3 text-sm" openLabel="Open" showIcon={false} onStatusChange={onStatusChange} />
                </li>
              );
            })}
          </ol>
        </details>
      ))}
    </div>
  );
}

export function WorkflowStatusFeed({ status, events }: WorkflowStatusFeedProps) {
  const actionable = events.filter((e) => e.severity === "blocked" || e.severity === "action_required");
  const routine = selectRoutineEvents(events);
  if (status.primary_state === "empty" && events.length === 0) {
    return (
      <section className="card p-5" aria-label="Workflow status">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div><h2 className="text-lg font-semibold">Workflow status</h2><p className="mt-1 text-sm text-muted">No action required</p></div>
          <Link href={status.next_action.href} className="btn-primary inline-flex justify-center text-sm">Upload statements</Link>
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
            <Badge variant={status.report_readiness.state === "blocked" ? "error" : "info"}>Report {sentenceFromSnake(status.report_readiness.state)}</Badge>
            {status.event_counts.action_required > 0 && <Badge variant="warning">{countLabel(status.event_counts.action_required, "action")}</Badge>}
            {status.event_counts.blocked > 0 && <Badge variant="error">{countLabel(status.event_counts.blocked, "blocked", "blocked")}</Badge>}
          </div>
        </div>
        <Link href={status.next_action.href} className="btn-secondary inline-flex justify-center text-sm">{nextActionLabel(status)}</Link>
      </div>
      {/* #2648: a long file name in a card wraps; it must not widen the page at 375 px. */}
      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="min-w-0 space-y-3">
          {actionable.slice(0, 3).map((e) => (
            <article key={e.id} className={cx("rounded-md border p-3 text-sm", e.severity === "blocked" ? "border-status-error bg-status-error-muted" : "border-status-warning bg-status-warning-muted")}>
              <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 className="font-medium [overflow-wrap:anywhere]">{humanizeWorkflowText(e.title)}</h3><p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">{humanizeWorkflowText(e.summary)}</p></div><Link href={e.action_href} className="btn-secondary shrink-0 px-3 py-1.5 text-xs" aria-label={`Open ${humanizeWorkflowText(e.title)}`}>Open</Link></div>
            </article>
          ))}
          {actionable.length === 0 && <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">No action required</div>}
        </div>
        <div className="min-w-0 rounded-md border border-border bg-surface-muted p-3">
          <div className="flex items-center gap-2"><Inbox className="h-4 w-4 text-muted" aria-hidden="true" /><h3 className="text-sm font-semibold">Routine automation</h3></div>
          <p className="mt-2 text-sm text-muted">{countLabel(routine.length, "routine event")}</p>
          {routine.length > 0 && <p className="mt-1 text-xs text-muted [overflow-wrap:anywhere]">Latest: {humanizeWorkflowText(routine[0]?.title)}</p>}
        </div>
      </div>
    </section>
  );
}

/** The one-line summary of the workflow: its state and the counts that need the user (#2648). */
export function workflowSummaryLine(status: WorkflowStatusResponse, eventTotal: number): string {
  return [
    labelFromSnake(status.primary_state),
    status.event_counts.blocked > 0 ? countLabel(status.event_counts.blocked, "blocker") : null,
    status.event_counts.action_required > 0 ? countLabel(status.event_counts.action_required, "action") : null,
    countLabel(eventTotal, "event"),
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Workflow notices for the /upload page (#2648): one summary line under the upload control.
 * The status feed and the full event timeline fold under it, so the file list stays near the top.
 */
export function WorkflowNotices() {
  const statusQuery = useWorkflowStatusQuery();
  const eventsQuery = useWorkflowEventsQuery(100, "page");
  const lifecycleMutation = useWorkflowLifecycleMutation();
  const events = eventsQuery.data?.items ?? [];
  const status = isWorkflowStatusResponse(statusQuery.data) ? statusQuery.data : null;
  if (statusQuery.isLoading || eventsQuery.isLoading) return <div className="mb-6 flex items-center gap-2 text-xs text-muted" role="status" aria-label="Workflow status"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />Loading workflow status...</div>;
  if (!status || !eventsQuery.data) return <Alert variant="warning" className="mb-6">Workflow status is unavailable.</Alert>;
  if (status.primary_state === "empty" && events.length === 0) return null;
  const needsUser = status.event_counts.blocked > 0 || status.event_counts.action_required > 0;
  return (
    <details data-testid="upload-workflow-summary" className="card group mb-6">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 text-sm">
        <span className="min-w-0 [overflow-wrap:anywhere]">
          <span className={cx("font-medium", needsUser && "text-[var(--warning)]")}>Workflow</span>
          {`: ${workflowSummaryLine(status, eventsQuery.data.total)}`}
        </span>
        <span className="shrink-0 text-xs text-[var(--accent)] group-open:hidden">Show details</span>
        <span className="hidden shrink-0 text-xs text-[var(--accent)] group-open:inline">Hide details</span>
      </summary>
      <div className="space-y-3 border-t border-[var(--border)] p-3">
        <WorkflowStatusFeed status={status} events={events} />
        {events.length > 0 && (
          <details className="card p-5" aria-label="Workflow event inbox">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3"><h2 className="text-lg font-semibold">Workflow events</h2><Badge variant="muted">{eventsQuery.data.total} total</Badge></summary>
            <div className="mt-4"><WorkflowInbox events={events} sessions={eventsQuery.data.sessions ?? []} onStatusChange={(eventId, nextStatus) => lifecycleMutation.mutate({ eventId, status: nextStatus })} /></div>
          </details>
        )}
      </div>
    </details>
  );
}

export function WorkflowNotificationCenter() {
  const [isOpen, setIsOpen] = useState(false);
  const statusQuery = useWorkflowStatusQuery();
  const eventsQuery = useWorkflowEventsQuery(50, "center", isOpen);
  const lifecycleMutation = useWorkflowLifecycleMutation();
  const status = isWorkflowStatusResponse(statusQuery.data) ? statusQuery.data : null;
  const counts = status?.event_counts ?? { unread: 0, action_required: 0, blocked: 0 };
  const attentionCount = counts.blocked + counts.action_required;
  const badgeCount = counts.unread || attentionCount;
  const ariaLabel = ["Workflow events", counts.unread ? countLabel(counts.unread, "unread") : null, counts.action_required ? countLabel(counts.action_required, "action") : null, counts.blocked ? countLabel(counts.blocked, "blocked", "blocked") : null].filter(Boolean).join(", ");
  return (
    <div className="flex h-11 items-center justify-end px-2">
      <button type="button" onClick={() => setIsOpen(true)} className={cx("relative inline-flex h-9 w-9 items-center justify-center rounded-md border transition-colors", attentionCount > 0 ? "border-status-warning bg-status-warning-muted text-status-warning" : "border-border text-muted hover:bg-surface-muted hover:text-content")} aria-label={ariaLabel || "Workflow events"} title="Workflow events">
        <Bell className="h-4 w-4" aria-hidden="true" />
        {badgeCount > 0 && <span className="absolute -right-1 -top-1 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-status-error px-1 text-[0.6875rem] font-semibold leading-5 text-content-inverse">{badgeCount > 99 ? "99+" : badgeCount}</span>}
      </button>
      <Sheet isOpen={isOpen} onClose={() => setIsOpen(false)} title="Workflow events" width="max-w-lg">
        <div className="space-y-4">
          {status && (
            <div className="rounded-md border border-border bg-surface-muted p-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <div><p className="text-xs uppercase tracking-wide text-muted">Current state</p><p className="font-semibold">{status.active_session?.title ?? labelFromSnake(status.primary_state)}</p>{status.active_session && <p className="mt-1 text-xs text-muted">{countLabel(status.active_session.source_count, "event")} in this session</p>}</div>
                <Badge variant={status.report_readiness.state === "blocked" ? "error" : "info"}>Report {sentenceFromSnake(status.report_readiness.state)}</Badge>
              </div>
            </div>
          )}
          {eventsQuery.isLoading && <div className="flex items-center gap-2 text-sm text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />Loading workflow events...</div>}
          {eventsQuery.isError && <Alert variant="error">Unable to load workflow events.</Alert>}
          {!eventsQuery.isLoading && !eventsQuery.isError && <WorkflowInbox events={eventsQuery.data?.items ?? []} sessions={eventsQuery.data?.sessions ?? []} onStatusChange={(eventId, nextStatus) => lifecycleMutation.mutate({ eventId, status: nextStatus })} />}
          <Link href="/audit?tab=needs-you" onClick={() => setIsOpen(false)} className="flex items-center justify-center gap-1 rounded-md border border-border px-3 py-2 text-sm text-content transition-colors hover:bg-surface-muted">Open everything that needs confirmation<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
        </div>
      </Sheet>
    </div>
  );
}
