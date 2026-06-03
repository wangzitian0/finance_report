"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bell,
  CheckCircle2,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  Inbox,
  Loader2,
  ShieldAlert,
} from "lucide-react";
import Sheet from "@/components/ui/Sheet";
import { Alert, Badge, EmptyState, IconButton } from "@/components/ui";
import {
  fetchWorkflowEvents,
  fetchWorkflowStatus,
  updateWorkflowEventStatus,
} from "@/lib/api";
import type {
  WorkflowEventResponse,
  WorkflowEventSeverity,
  WorkflowEventStatus,
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

function routineEvents(events: WorkflowEventResponse[]) {
  return events.filter((event) => event.severity !== "blocked" && event.severity !== "action_required");
}

interface WorkflowEventGroupProps {
  title: string;
  events: WorkflowEventResponse[];
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
  showActions?: boolean;
}

function WorkflowEventGroup({
  title,
  events,
  onStatusChange,
  showActions = true,
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
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Link
                      href={event.action_href}
                      className="btn-secondary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      Open {event.title}
                    </Link>
                    {showActions && event.status === "unread" && (
                      <button
                        type="button"
                        className="btn-ghost px-3 py-1.5 text-xs"
                        aria-label={`Mark ${event.title} as read`}
                        onClick={() => onStatusChange?.(event.id, "read")}
                      >
                        Mark as read
                      </button>
                    )}
                    {showActions && event.status !== "archived" && (
                      <button
                        type="button"
                        className="btn-ghost px-3 py-1.5 text-xs"
                        onClick={() => onStatusChange?.(event.id, "archived")}
                      >
                        Archive
                        <span className="sr-only"> {event.title}</span>
                      </button>
                    )}
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
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}

export function WorkflowInbox({ events, onStatusChange }: WorkflowInboxProps) {
  const grouped = useMemo(
    () => ({
      blocked: events.filter((event) => event.severity === "blocked"),
      actionRequired: events.filter((event) => event.severity === "action_required"),
      routine: routineEvents(events),
    }),
    [events],
  );

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

  return (
    <div className="space-y-5">
      <WorkflowEventGroup title="Blocked" events={grouped.blocked} onStatusChange={onStatusChange} />
      <WorkflowEventGroup title="Action required" events={grouped.actionRequired} onStatusChange={onStatusChange} />
      <WorkflowEventGroup title="Routine automation" events={grouped.routine} onStatusChange={onStatusChange} />
    </div>
  );
}

export function WorkflowNotificationCenter() {
  const [isOpen, setIsOpen] = useState(false);
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [events, setEvents] = useState<WorkflowEventResponse[]>([]);
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
        if (!cancelled) setEvents(nextEvents.items);
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
  return (
    <div className="rounded-md border border-border bg-surface-muted p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">Current state</p>
          <p className="font-semibold">{labelFromSnake(status.primary_state)}</p>
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
  const primaryLabel = status.next_action.type === "upload" ? "Upload statements" : "Open next action";
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

export function WorkflowStatusFeedPanel() {
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [events, setEvents] = useState<WorkflowEventResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadWorkflowFeed() {
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

    void loadWorkflowFeed();

    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) {
    return (
      <section className="card p-5" aria-label="Workflow status">
        <div className="flex items-center gap-2 text-sm text-muted" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading workflow status...
        </div>
      </section>
    );
  }

  if (error || !status) {
    return (
      <section className="card p-5" aria-label="Workflow status">
        <div className="alert-warning">Workflow status is unavailable.</div>
      </section>
    );
  }

  return <WorkflowStatusFeed status={status} events={events} />;
}

export function WorkflowArchiveButton({
  event,
  onArchive,
}: {
  event: WorkflowEventResponse;
  onArchive: (eventId: string) => void;
}) {
  return <IconButton icon={Archive} label={`Archive ${event.title}`} onClick={() => onArchive(event.id)} />;
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
              onStatusChange={(eventId, status) => lifecycleMutation.mutate({ eventId, status })}
            />
          )}
        </section>
      </div>
    </div>
  );
}
