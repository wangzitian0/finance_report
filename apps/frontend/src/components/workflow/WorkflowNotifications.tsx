"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Bell, Check, ChevronRight, ExternalLink, Inbox, Loader2 } from "lucide-react";

import Sheet from "@/components/ui/Sheet";
import { Alert, Badge, EmptyState, cx } from "@/components/ui";
import { isWorkflowStatusResponse, useWorkflowEventsQuery, useWorkflowLifecycleMutation, useWorkflowStatusQuery } from "@/hooks/useWorkflowStatus";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowEventResponse, WorkflowEventStatus, WorkflowSessionSummaryResponse, WorkflowStatusResponse } from "@/lib/types";
import {
  formatEventTime, groupEventsBySession, humanizeWorkflowText, labelFromSnake, nextActionLabel, nextActionSummary,
  routineEvents as selectRoutineEvents, sentenceFromSnake, severityBadgeVariant, severityIcon, workflowEventCardClass, workflowStateCopy,
} from "./workflowFormat";

export type FlowStep = "upload" | "review" | "reports";
const STEPS: { key: FlowStep; label: string; href: string }[] = [
  { key: "upload", label: "Upload", href: "/upload" },
  { key: "review", label: "Review & approve", href: "/notifications" },
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
      <ol className="flex items-center gap-1 text-sm">
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
          <h1 className="text-sm font-semibold">{sessionTitle}</h1>
          <div className="sr-only">{sessionTitle !== "Upload to report" && <h2>Upload to report</h2>}<h2>Workflow status</h2></div>
          <Badge variant={severityBadgeVariant(status.primary_state === "blocked" ? "blocked" : "info")}>{labelFromSnake(status.primary_state)}</Badge>
          <span className="text-xs text-muted">{primaryCopy}</span>
          {Boolean(summaryText && summaryText !== primaryCopy) && <span className="text-xs text-muted hidden sm:inline">{summaryText}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {blocked.length > 0 && <span>Blocked: {humanizeWorkflowText(blocked[0].title)}</span>}
          {actions.length > 0 && <span>Action required: {humanizeWorkflowText(actions[0].title)}</span>}
          {routine.length > 0 && <span><strong className="font-medium">Routine automation</strong>: {routine.length} {routine.length === 1 ? "routine event" : "routine events"} ({humanizeWorkflowText(routine[0].title)})</span>}
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
  const eventsQuery = useWorkflowEventsQuery(5, "home");
  if (statusQuery.isLoading || eventsQuery.isLoading) return <section className="card px-3 py-2.5 animate-pulse" aria-label="Upload-to-report home" role="status" aria-busy="true"><div className="h-5 w-48 rounded bg-muted/20" /></section>;
  if (statusQuery.isError || eventsQuery.isError || !status) {
    return (
      <section className="card px-3 py-2.5" aria-label="Upload-to-report home">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div><h1 className="text-sm font-semibold">Upload to report</h1><p className="text-xs text-muted">Workflow status is unavailable. You can still upload files or open reports.</p></div>
          <div className="flex flex-wrap gap-2"><Link href="/upload" className="btn-primary px-2.5 py-1 text-xs">Upload statements</Link><Link href="/reports" className="btn-secondary px-2.5 py-1 text-xs">Open reports</Link></div>
        </div>
      </section>
    );
  }
  return <UploadToReportHome status={status} events={eventsQuery.data?.items ?? []} />;
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
            <div className="flex flex-wrap items-center gap-1.5"><h4 className="text-xs font-medium">{displayTitle}</h4><Badge variant={severityBadgeVariant(event.severity)}>{labelFromSnake(event.severity)}</Badge></div>
            <time className="text-[11px] text-muted" dateTime={event.occurred_at}>{formatEventTime(event.occurred_at)}</time>
          </div>
          <p className="mt-0.5 text-xs text-muted">{displaySummary}</p>
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
              <div className="min-w-0"><h3 className="text-sm font-semibold">{session.title}</h3><p className="mt-1 text-xs text-muted">{session.summary}</p></div>
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
      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="space-y-3">
          {actionable.slice(0, 3).map((e) => (
            <article key={e.id} className={cx("rounded-md border p-3 text-sm", e.severity === "blocked" ? "border-status-error bg-status-error-muted" : "border-status-warning bg-status-warning-muted")}>
              <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 className="font-medium">{e.title}</h3><p className="mt-1 text-sm text-muted">{e.summary}</p></div><Link href={e.action_href} className="btn-secondary shrink-0 px-3 py-1.5 text-xs" aria-label={`Open ${e.title}`}>Open</Link></div>
            </article>
          ))}
          {actionable.length === 0 && <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">No action required</div>}
        </div>
        <div className="rounded-md border border-border bg-surface-muted p-3">
          <div className="flex items-center gap-2"><Inbox className="h-4 w-4 text-muted" aria-hidden="true" /><h3 className="text-sm font-semibold">Routine automation</h3></div>
          <p className="mt-2 text-sm text-muted">{countLabel(routine.length, "routine event")}</p>
          {routine.length > 0 && <p className="mt-1 text-xs text-muted">Latest: {routine[0]?.title}</p>}
        </div>
      </div>
    </section>
  );
}

export function WorkflowEventsPageContent() {
  const statusQuery = useWorkflowStatusQuery();
  const eventsQuery = useWorkflowEventsQuery(100, "page");
  const lifecycleMutation = useWorkflowLifecycleMutation();
  return (
    <div className="p-6">
      <div className="page-header flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div><h1 className="page-title">Notifications</h1><p className="page-description">Your action center — everything that needs your review across uploads, reconciliation, and reports.</p></div>
        <Link href="/upload" className="btn-primary inline-flex justify-center text-sm">Upload statements</Link>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          {statusQuery.isLoading || eventsQuery.isLoading ? <section className="card p-5" aria-label="Workflow status"><div className="flex items-center gap-2 text-sm text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />Loading workflow status...</div></section>
            : statusQuery.data && eventsQuery.data ? <WorkflowStatusFeed status={statusQuery.data} events={eventsQuery.data.items} />
            : <section className="card p-5" aria-label="Workflow status"><div className="alert-warning">Workflow status is unavailable.</div></section>}
        </div>
        <section className="card p-5" aria-label="Workflow event inbox">
          <div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">Workflow events</h2><Badge variant="muted">{eventsQuery.data?.total ?? 0} total</Badge></div>
          {eventsQuery.isLoading && <div className="flex items-center gap-2 text-sm text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />Loading workflow events...</div>}
          {eventsQuery.isError && <Alert variant="error">Unable to load workflow events.</Alert>}
          {eventsQuery.data && <WorkflowInbox events={eventsQuery.data.items} sessions={eventsQuery.data.sessions} onStatusChange={(eventId, status) => lifecycleMutation.mutate({ eventId, status })} />}
        </section>
      </div>
    </div>
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
          <Link href="/audit" onClick={() => setIsOpen(false)} className="flex items-center justify-center gap-1 rounded-md border border-border px-3 py-2 text-sm text-content transition-colors hover:bg-surface-muted">Open everything that needs confirmation<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
        </div>
      </Sheet>
    </div>
  );
}
