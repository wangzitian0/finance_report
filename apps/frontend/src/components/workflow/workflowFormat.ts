import { CheckCircle2, CircleAlert, CircleCheck, ShieldAlert } from "lucide-react";

import { cx } from "@/components/ui";
import type {
  WorkflowEventResponse,
  WorkflowEventSeverity,
  WorkflowSessionSummaryResponse,
  WorkflowStatusResponse,
} from "@/lib/types";

/**
 * Pure display/grouping helpers for the workflow notification surfaces (was
 * inline in components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export function severityBadgeVariant(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return "error";
  if (severity === "action_required" || severity === "warning") return "warning";
  if (severity === "success") return "success";
  return "info";
}

export function severityIcon(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return ShieldAlert;
  if (severity === "action_required" || severity === "warning") return CircleAlert;
  if (severity === "success") return CircleCheck;
  return CheckCircle2;
}

export function workflowEventCardClass(event: WorkflowEventResponse) {
  return cx(
    "rounded-md border p-3 text-sm",
    event.severity === "blocked" && "border-status-error bg-status-error-muted",
    event.severity === "action_required" && "border-status-warning bg-status-warning-muted",
    event.severity !== "blocked" && event.severity !== "action_required" && "border-border bg-surface-card",
  );
}

export function labelFromSnake(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function sentenceFromSnake(value: string) {
  return value.replace(/_/g, " ");
}

export function formatEventTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function routineEvents(events: WorkflowEventResponse[]) {
  return events.filter((event) => event.severity !== "blocked" && event.severity !== "action_required");
}

export function nextActionLabel(status: WorkflowStatusResponse) {
  if (status.next_action.label) return status.next_action.label;
  if (status.next_action.type === "upload") return "Upload statements";
  if (status.next_action.type === "review_required") return "Review required";
  if (status.next_action.type === "resolve_blocker") return "Resolve blocker";
  if (status.next_action.type === "open_report") return "Open report package";
  if (status.next_action.type === "wait") return "View processing";
  return "Open workflow";
}

export function nextActionSummary(status: WorkflowStatusResponse) {
  return status.next_action.summary;
}

export function workflowStateCopy(status: WorkflowStatusResponse) {
  if (status.primary_state === "blocked") return "A blocker is holding report readiness.";
  if (status.primary_state === "needs_action") return "Review the required action so automation can continue.";
  if (status.primary_state === "processing") return "Automation is processing uploaded source files.";
  if (status.primary_state === "ready") return "Reports are ready to inspect.";
  return "Upload files to start the automated reporting workflow.";
}

export function fallbackSession(events: WorkflowEventResponse[]): WorkflowSessionSummaryResponse {
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

export function groupEventsBySession(events: WorkflowEventResponse[], sessions: WorkflowSessionSummaryResponse[]) {
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
