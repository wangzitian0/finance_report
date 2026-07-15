"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui";
import type { WorkflowEventResponse, WorkflowEventStatus } from "@/lib/types";

import { formatEventTime, labelFromSnake, severityBadgeVariant, severityIcon, workflowEventCardClass } from "./workflowFormat";

/**
 * Single event card + a titled group of cards (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export function WorkflowEventCard({
  event,
  className = workflowEventCardClass(event),
  openLabel = `Open ${event.title}`,
  showIcon = true,
  onStatusChange,
}: {
  event: WorkflowEventResponse;
  className?: string;
  openLabel?: string;
  showIcon?: boolean;
  onStatusChange?: (eventId: string, status: WorkflowEventStatus) => void;
}) {
  const Icon = severityIcon(event.severity);
  return (
    <article className={className}>
      <div className="flex min-w-0 items-start gap-3">
        {showIcon && <Icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />}
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
              aria-label={`Open ${event.title}`}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              {openLabel}
            </Link>
            {event.status === "unread" && onStatusChange && (
              <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => onStatusChange(event.id, "read")}>
                Mark as read
              </button>
            )}
            {event.status !== "archived" && onStatusChange && (
              <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => onStatusChange(event.id, "archived")}>
                Archive
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

export function WorkflowEventGroup({ title, events }: { title: string; events: WorkflowEventResponse[] }) {
  if (events.length === 0) return null;
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="space-y-2">
        {events.map((event) => (
          <WorkflowEventCard key={event.id} event={event} />
        ))}
      </div>
    </section>
  );
}
