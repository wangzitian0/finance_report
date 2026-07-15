"use client";

import Link from "next/link";

import { Badge, EmptyState } from "@/components/ui";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowEventResponse, WorkflowEventStatus, WorkflowSessionSummaryResponse } from "@/lib/types";

import { WorkflowEventCard } from "./WorkflowEventCard";
import { formatEventTime, groupEventsBySession, severityIcon } from "./workflowFormat";

/**
 * Session-grouped event inbox (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

interface WorkflowInboxProps {
  events: WorkflowEventResponse[];
  sessions?: WorkflowSessionSummaryResponse[];
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
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
              <WorkflowEventCard
                event={event}
                className="min-w-0 flex-1 rounded-md border border-border bg-surface-muted p-3 text-sm"
                openLabel="Open"
                showIcon={false}
                onStatusChange={onStatusChange}
              />
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
          <Link href="/upload" className="btn-primary inline-flex">
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
        <WorkflowSessionTimeline key={session.id} session={session} events={sessionEvents} onStatusChange={onStatusChange} />
      ))}
    </div>
  );
}
