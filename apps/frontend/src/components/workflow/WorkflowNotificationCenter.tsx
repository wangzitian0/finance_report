"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Bell, Loader2 } from "lucide-react";

import Sheet from "@/components/ui/Sheet";
import { Alert, Badge, cx } from "@/components/ui";
import {
  isWorkflowStatusResponse,
  useWorkflowEventsQuery,
  useWorkflowLifecycleMutation,
  useWorkflowStatusQuery,
} from "@/hooks/useWorkflowStatus";
import { countLabel } from "@/lib/statusLabels";
import type { WorkflowStatusResponse } from "@/lib/types";

import { WorkflowInbox } from "./WorkflowInbox";
import { labelFromSnake, sentenceFromSnake } from "./workflowFormat";

/**
 * Bell-icon notification center (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

function WorkflowStatusSummary({ status }: { status: WorkflowStatusResponse }) {
  const activeSession = status.active_session;
  return (
    <div className="rounded-md border border-border bg-surface-muted p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">Current state</p>
          <p className="font-semibold">{activeSession?.title ?? labelFromSnake(status.primary_state)}</p>
          {activeSession && (
            <p className="mt-1 text-xs text-muted">{countLabel(activeSession.source_count, "event")} in this session</p>
          )}
        </div>
        <Badge variant={status.report_readiness.state === "blocked" ? "error" : "info"}>
          Report {sentenceFromSnake(status.report_readiness.state)}
        </Badge>
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
  const events = eventsQuery.data?.items ?? [];
  const sessions = eventsQuery.data?.sessions ?? [];

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
          {status && <WorkflowStatusSummary status={status} />}
          {eventsQuery.isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading workflow events...
            </div>
          )}
          {eventsQuery.isError && <Alert variant="error">Unable to load workflow events.</Alert>}
          {!eventsQuery.isLoading && !eventsQuery.isError && (
            <WorkflowInbox
              events={events}
              sessions={sessions}
              onStatusChange={(eventId, nextStatus) => {
                lifecycleMutation.mutate({ eventId, status: nextStatus });
              }}
            />
          )}
          {/* EPIC-022 AC22.6.3: the bell connects to the full, confidence-ranked
              attention queue so the two surfaces stay consistent. */}
          <Link
            href="/attention"
            onClick={() => setIsOpen(false)}
            className="flex items-center justify-center gap-1 rounded-md border border-border px-3 py-2 text-sm text-content transition-colors hover:bg-surface-muted"
          >
            Open the full attention queue
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </Sheet>
    </div>
  );
}
