"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Bell,
  CheckCircle2,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  FileCheck2,
  Inbox,
  Loader2,
  UploadCloud,
  ShieldAlert,
} from "lucide-react";
import Sheet from "@/components/ui/Sheet";
import { Alert, Badge, EmptyState, type BadgeVariant } from "@/components/ui";
import {
  fetchWorkflowEvents,
  fetchWorkflowStatus,
  updateWorkflowEventStatus,
} from "@/lib/api";
import type {
  WorkflowEventResponse,
  WorkflowEventSeverity,
  WorkflowEventStatus,
  WorkflowSessionSummaryResponse,
  WorkflowStatusResponse,
} from "@/lib/types";

const STATUS_QUERY_KEY = ["workflow", "status"] as const;
const EVENTS_QUERY_KEY = ["workflow", "events"] as const;

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function severityBadgeVariant(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return "error";
  if (severity === "action_required" || severity === "warning") return "warning";
  if (severity === "success") return "success";
  return "info";
}

function severityIcon(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return ShieldAlert;
  if (severity === "action_required" || severity === "warning") return CircleAlert;
  if (severity === "success") return CircleCheck;
  return CheckCircle2;
}

function labelFromSnake(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function sentenceFromSnake(value: string) {
  return value.replace(/_/g, " ");
}

function countLabel(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function formatEventTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function routineEvents(events: WorkflowEventResponse[]) {
  return events.filter((event) => event.severity !== "blocked" && event.severity !== "action_required");
}

function nextActionLabel(status: WorkflowStatusResponse) {
  if (status.next_action.label) return status.next_action.label;
  if (status.next_action.type === "upload") return "Upload statements";
  if (status.next_action.type === "review_required") return "Review required";
  if (status.next_action.type === "resolve_blocker") return "Resolve blocker";
  if (status.next_action.type === "open_report") return "Open report package";
  if (status.next_action.type === "wait") return "View processing";
  return "Open workflow";
}

function nextActionSummary(status: WorkflowStatusResponse) {
  return status.next_action.summary || workflowStateCopy(status);
}

function workflowStateCopy(status: WorkflowStatusResponse) {
  if (status.primary_state === "blocked") return "A blocker is holding report readiness.";
  if (status.primary_state === "needs_action") return "Review the required action so automation can continue.";
  if (status.primary_state === "processing") return "Automation is processing uploaded source files.";
  if (status.primary_state === "ready") return "Reports are ready to inspect.";
  return "Upload files to start the automated reporting workflow.";
}

function readinessVariant(state: WorkflowStatusResponse["report_readiness"]["state"]): BadgeVariant {
  if (state === "blocked" || state === "stale") return "error";
  if (state === "processing") return "warning";
  if (state === "ready") return "success";
  return "info";
}

interface WorkflowEventGroupProps {
  title: string;
  events: WorkflowEventResponse[];
}

function WorkflowEventGroup({
  title,
  events,
}: WorkflowEventGroupProps) {
  if (events.length === 0) return null;

  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="space-y-2">
        {events.map((event) => {
          const Icon = severityIcon(event.severity);
          return (
            <article
              key={event.id}
              className={cx(
                "rounded-md border p-3 text-sm",
                event.severity === "blocked" && "border-status-error bg-status-error-muted",
                event.severity === "action_required" && "border-status-warning bg-status-warning-muted",
                event.severity !== "blocked" &&
                  event.severity !== "action_required" &&
                  "border-border bg-surface-card",
              )}
            >
              <div className="flex min-w-0 items-start gap-3">
                <Icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="font-medium">{event.title}</h4>
                    <Badge variant={severityBadgeVariant(event.severity)}>{labelFromSnake(event.severity)}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-muted">{event.summary}</p>
                  <time className="mt-2 block text-xs text-muted" dateTime={event.occurred_at}>
                    {formatEventTime(event.occurred_at)}
                  </time>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Link
                      href={event.action_href}
                      className="btn-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      Open {event.title}
                    </Link>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

interface WorkflowInboxProps {
  events: WorkflowEventResponse[];
  sessions?: WorkflowSessionSummaryResponse[];
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}

function fallbackSession(events: WorkflowEventResponse[]): WorkflowSessionSummaryResponse {
  return {
    id: "legacy-workflow-session",
    status: "active",
    title: "Workflow session",
    summary: "Legacy workflow events without a stored session.",
    started_at: events[events.length - 1]?.occurred_at ?? new Date().toISOString(),
    last_event_at: events[0]?.occurred_at ?? null,
    source_count: events.length,
    primary_state: events.some((event) => event.severity === "blocked")
      ? "blocked"
      : events.some((event) => event.severity === "action_required")
        ? "needs_action"
        : events.length
          ? "processing"
          : "empty",
    report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
    event_counts: {
      unread: events.filter((event) => event.status === "unread").length,
      action_required: events.filter((event) => event.severity === "action_required").length,
      blocked: events.filter((event) => event.severity === "blocked").length,
    },
  };
}

function groupEventsBySession(events: WorkflowEventResponse[], sessions: WorkflowSessionSummaryResponse[]) {
  const sessionById = new Map(sessions.map((session) => [session.id, session]));
  const grouped = new Map<string, WorkflowEventResponse[]>();
  for (const event of events) {
    const sessionId = event.session_id ?? "legacy-workflow-session";
    grouped.set(sessionId, [...(grouped.get(sessionId) ?? []), event]);
  }
  return Array.from(grouped.entries()).map(([sessionId, sessionEvents]) => ({
    session: sessionById.get(sessionId) ?? fallbackSession(sessionEvents),
    events: sessionEvents.sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)),
  }));
}

function WorkflowSessionTimeline({
  session,
  events,
  onStatusChange,
}: {
  session: WorkflowSessionSummaryResponse;
  events: WorkflowEventResponse[];
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}) {
  const latest = session.last_event_at ? formatEventTime(session.last_event_at) : "No events yet";
  return (
    <details className="rounded-md border border-border bg-surface-card p-3" open={session.status === "active"}>
      <summary className="cursor-pointer list-none">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">{session.title}</h3>
            <p className="mt-1 text-xs text-muted">{session.summary}</p>
          </div>
          <Badge variant={session.event_counts.blocked > 0 ? "error" : session.event_counts.action_required > 0 ? "warning" : "muted"}>
            {countLabel(events.length, "event")}
          </Badge>
        </div>
        <p className="mt-2 text-xs text-muted">Latest: {latest}</p>
      </summary>
      <ol className="mt-4 space-y-3" aria-label={`${session.title} timeline`}>
        {events.map((event) => {
          const Icon = severityIcon(event.severity);
          return (
            <li key={event.id} className="flex gap-3">
              <div className="mt-1 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-surface-muted">
                <Icon className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1 rounded-md border border-border bg-surface-muted p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <time className="text-xs text-muted" dateTime={event.occurred_at}>
                    {formatEventTime(event.occurred_at)}
                  </time>
                  <Badge variant={severityBadgeVariant(event.severity)}>{labelFromSnake(event.severity)}</Badge>
                </div>
                <h4 className="mt-2 text-sm font-medium">{event.title}</h4>
                <p className="mt-1 text-sm text-muted">{event.summary}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Link href={event.action_href} className="btn-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs">
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    Open
                  </Link>
                  {event.status === "unread" && (
                    <button
                      type="button"
                      className="btn-ghost px-3 py-1.5 text-xs"
                      onClick={() => onStatusChange?.(event.id, "read")}
                    >
                      Mark as read
                    </button>
                  )}
                  {event.status !== "archived" && (
                    <button
                      type="button"
                      className="btn-ghost px-3 py-1.5 text-xs"
                      onClick={() => onStatusChange?.(event.id, "archived")}
                    >
                      Archive
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

export function WorkflowInbox({ events, sessions = [], onStatusChange }: WorkflowInboxProps) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="No action required"
        description="Workflow events will appear here when review or blockers need attention."
        action={
          <Link href="/statements/upload" className="btn-primary inline-flex">
            Upload statements
          </Link>
        }
      />
    );
  }

  const sessionGroups = groupEventsBySession(events, sessions);
  return (
    <div className="space-y-3">
      {sessionGroups.map(({ session, events: sessionEvents }) => (
        <WorkflowSessionTimeline
          key={session.id}
          session={session}
          events={sessionEvents}
          onStatusChange={onStatusChange}
        />
      ))}
    </div>
  );
}

export function WorkflowNotificationCenter() {
  const [isOpen, setIsOpen] = useState(false);
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [events, setEvents] = useState<WorkflowEventResponse[]>([]);
  const [sessions, setSessions] = useState<WorkflowSessionSummaryResponse[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const nextStatus = await fetchWorkflowStatus();
        if (!cancelled) setStatus(nextStatus);
      } catch {
        if (!cancelled) setStatus(null);
      }
    }

    void loadStatus();
    const interval = window.setInterval(loadStatus, 30000);
    window.addEventListener("focus", loadStatus);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", loadStatus);
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    async function loadEvents() {
      setEventsLoading(true);
      setEventsError(false);
      try {
        const nextEvents = await fetchWorkflowEvents({ limit: 50 });
        if (!cancelled) {
          setEvents(nextEvents.items);
          setSessions(nextEvents.sessions);
        }
      } catch {
        if (!cancelled) setEventsError(true);
      } finally {
        if (!cancelled) setEventsLoading(false);
      }
    }

    void loadEvents();

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  async function updateEventLifecycle(eventId: string, nextStatus: WorkflowEventStatus) {
    await updateWorkflowEventStatus(eventId, nextStatus);
    const [nextStatusSummary, nextEvents] = await Promise.all([
      fetchWorkflowStatus(),
      fetchWorkflowEvents({ limit: 50 }),
    ]);
    setStatus(nextStatusSummary);
    setEvents(nextEvents.items);
    setSessions(nextEvents.sessions);
  }

  const counts = status?.event_counts ?? { unread: 0, action_required: 0, blocked: 0 };
  const attentionCount = counts.blocked + counts.action_required;
  const badgeCount = counts.unread || attentionCount;
  const ariaLabel = [
    "Workflow events",
    counts.unread ? countLabel(counts.unread, "unread") : null,
    counts.action_required ? countLabel(counts.action_required, "action") : null,
    counts.blocked ? countLabel(counts.blocked, "blocked", "blocked") : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="flex h-11 items-center justify-end px-2">
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className={cx(
          "relative inline-flex h-9 w-9 items-center justify-center rounded-md border transition-colors",
          attentionCount > 0
            ? "border-status-warning bg-status-warning-muted text-status-warning"
            : "border-border text-muted hover:bg-surface-muted hover:text-content",
        )}
        aria-label={ariaLabel || "Workflow events"}
        title="Workflow events"
      >
        <Bell className="h-4 w-4" aria-hidden="true" />
        {badgeCount > 0 && (
          <span className="absolute -right-1 -top-1 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-status-error px-1 text-[0.6875rem] font-semibold leading-5 text-content-inverse">
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </button>

      <Sheet isOpen={isOpen} onClose={() => setIsOpen(false)} title="Workflow events" width="max-w-lg">
        <div className="space-y-4">
          {status && (
            <WorkflowStatusSummary status={status} />
          )}
          {eventsLoading && (
            <div className="flex items-center gap-2 text-sm text-muted" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading workflow events...
            </div>
          )}
          {eventsError && <Alert variant="error">Unable to load workflow events.</Alert>}
          {!eventsLoading && !eventsError && (
            <WorkflowInbox
              events={events}
              sessions={sessions}
              onStatusChange={(eventId, nextStatus) => {
                void updateEventLifecycle(eventId, nextStatus);
              }}
            />
          )}
        </div>
      </Sheet>
    </div>
  );
}

function WorkflowStatusSummary({ status }: { status: WorkflowStatusResponse }) {
  const activeSession = status.active_session;
  return (
    <div className="rounded-md border border-border bg-surface-muted p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">Current state</p>
          <p className="font-semibold">{activeSession?.title ?? labelFromSnake(status.primary_state)}</p>
          {activeSession && (
            <p className="mt-1 text-xs text-muted">
              {countLabel(activeSession.source_count, "event")} in this session
            </p>
          )}
        </div>
        <Badge variant={status.report_readiness.state === "blocked" ? "error" : "info"}>
          Report {sentenceFromSnake(status.report_readiness.state)}
        </Badge>
      </div>
    </div>
  );
}

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
                <Link href={event.action_href} className="btn-secondary shrink-0 px-3 py-1.5 text-xs">
                  Open
                </Link>
              </div>
            </article>
          ))}
          {actionableEvents.length === 0 && (
            <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">
              No action required
            </div>
          )}
        </div>

        <div className="rounded-md border border-border bg-surface-muted p-3">
          <div className="flex items-center gap-2">
            <Inbox className="h-4 w-4 text-muted" aria-hidden="true" />
            <h3 className="text-sm font-semibold">Routine automation</h3>
          </div>
          <p className="mt-2 text-sm text-muted">{countLabel(routineCount, "routine event")}</p>
          {routineCount > 0 && (
            <p className="mt-1 text-xs text-muted">
              Latest: {routineEvents(events)[0]?.title}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

export function UploadToReportHome({ status, events }: WorkflowStatusFeedProps) {
  const groupedEvents = {
    blocked: events.filter((event) => event.severity === "blocked"),
    actionRequired: events.filter((event) => event.severity === "action_required"),
    routine: routineEvents(events),
  };
  const primaryLabel = nextActionLabel(status);
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
          <p className="text-xs uppercase tracking-wide text-muted">Upload Pipeline</p>
          <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold">{activeSession?.title ?? "Upload to report"}</h1>
              <p className="mt-2 max-w-2xl text-sm text-muted">{workflowStateCopy(status)}</p>
              <p className="mt-2 max-w-2xl text-sm font-medium">{nextActionSummary(status)}</p>
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
              <Link
                href={status.next_action.href}
                className="btn-primary inline-flex items-center justify-center gap-2 text-sm"
              >
                {primaryIsUpload ? (
                  <UploadCloud className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                )}
                {primaryLabel}
              </Link>
              <Link href="/events" className="btn-secondary inline-flex items-center justify-center gap-2 text-sm">
                <Inbox className="h-4 w-4" aria-hidden="true" />
                Session history
              </Link>
            </div>
          </div>
        </div>

        <Link
          href={status.report_readiness.href}
          className="card block p-5 transition-colors hover:border-[var(--accent)]"
          aria-label="Report readiness"
        >
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
            <div className="rounded-md border border-border bg-surface-muted p-3 text-sm text-muted">
              No action required
            </div>
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
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [events, setEvents] = useState<WorkflowEventResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadUploadHome() {
      setIsLoading(true);
      setError(false);
      try {
        const [nextStatus, nextEvents] = await Promise.all([
          fetchWorkflowStatus(),
          fetchWorkflowEvents({ limit: 5 }),
        ]);
        if (!cancelled) {
          setStatus(nextStatus);
          setEvents(nextEvents.items);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void loadUploadHome();

    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) {
    return (
      <section className="card p-5" aria-label="Upload-to-report home">
        <div className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading upload-to-report workflow...
        </div>
      </section>
    );
  }

  if (error || !status) {
    return (
      <section className="card p-5" aria-label="Upload-to-report home">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold">Upload to report</h1>
            <p className="mt-1 text-sm text-muted">Workflow status is unavailable. You can still upload files or open reports.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/statements/upload" className="btn-primary text-sm">Upload statements</Link>
            <Link href="/reports" className="btn-secondary text-sm">Open reports</Link>
          </div>
        </div>
      </section>
    );
  }

  return <UploadToReportHome status={status} events={events} />;
}

export function WorkflowEventsPageContent() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: fetchWorkflowStatus,
  });
  const eventsQuery = useQuery({
    queryKey: [...EVENTS_QUERY_KEY, "page"],
    queryFn: () => fetchWorkflowEvents({ limit: 100 }),
  });
  const lifecycleMutation = useMutation({
    mutationFn: ({ eventId, status }: { eventId: string; status: WorkflowEventStatus }) =>
      updateWorkflowEventStatus(eventId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: EVENTS_QUERY_KEY });
    },
  });

  return (
    <div className="p-6">
      <div className="page-header flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="page-title">Events</h1>
          <p className="page-description">Workflow attention for upload, review, reconciliation, and reports</p>
        </div>
        <Link href="/statements/upload" className="btn-primary inline-flex justify-center text-sm">
          Upload statements
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          {statusQuery.isLoading || eventsQuery.isLoading ? (
            <section className="card p-5" aria-label="Workflow status">
              <div className="flex items-center gap-2 text-sm text-muted" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading workflow status...
              </div>
            </section>
          ) : statusQuery.data && eventsQuery.data ? (
            <WorkflowStatusFeed status={statusQuery.data} events={eventsQuery.data.items} />
          ) : (
            <section className="card p-5" aria-label="Workflow status">
              <div className="alert-warning">Workflow status is unavailable.</div>
            </section>
          )}
        </div>

        <section className="card p-5" aria-label="Workflow event inbox">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Workflow events</h2>
            <Badge variant="muted">{eventsQuery.data?.total ?? 0} total</Badge>
          </div>
          {eventsQuery.isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading workflow events...
            </div>
          )}
          {eventsQuery.isError && <Alert variant="error">Unable to load workflow events.</Alert>}
          {eventsQuery.data && (
            <WorkflowInbox
              events={eventsQuery.data.items}
              sessions={eventsQuery.data.sessions}
              onStatusChange={(eventId, status) => lifecycleMutation.mutate({ eventId, status })}
            />
          )}
        </section>
      </div>
    </div>
  );
}
