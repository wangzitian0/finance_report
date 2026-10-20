"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui";
import type { WorkflowEventResponse, WorkflowEventStatus } from "@/lib/types";

import { formatEventTime, humanizeWorkflowText, labelFromSnake, severityBadgeVariant, severityIcon, workflowEventCardClass } from "./workflowFormat";

/**
 * Single workflow event card (extracted from
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export function WorkflowEventCard({
  event,
  className = workflowEventCardClass(event),
  openLabel,
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
  const displayTitle = humanizeWorkflowText(event.title);
  const displaySummary = humanizeWorkflowText(event.summary);
  const resolvedOpenLabel = openLabel ?? `Open ${displayTitle}`;
  return (
    <article className={`${className} !p-2.5`}>
      <div className="flex min-w-0 items-start gap-2">
        {showIcon && <Icon className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted" aria-hidden="true" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <h4 className="text-xs font-medium">{displayTitle}</h4>
              <Badge variant={severityBadgeVariant(event.severity)}>{labelFromSnake(event.severity)}</Badge>
            </div>
            <time className="text-[11px] text-muted" dateTime={event.occurred_at}>
              {formatEventTime(event.occurred_at)}
            </time>
          </div>
          <p className="mt-0.5 text-xs text-muted">{displaySummary}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Link
              href={event.action_href}
              className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-[11px]"
              aria-label={`Open ${displayTitle}`}
            >
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
              {resolvedOpenLabel}
            </Link>
            {event.status === "unread" && onStatusChange && (
              <button type="button" className="btn-ghost px-2 py-1 text-[11px]" onClick={() => onStatusChange(event.id, "read")}>
                Mark as read
              </button>
            )}
            {event.status !== "archived" && onStatusChange && (
              <button type="button" className="btn-ghost px-2 py-1 text-[11px]" onClick={() => onStatusChange(event.id, "archived")}>
                Archive
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
