import { CheckCircle2, CircleAlert, CircleCheck, ShieldAlert } from "lucide-react";
import { cx } from "@/components/ui";
import type { WorkflowEventResponse, WorkflowEventSeverity, WorkflowSessionSummaryResponse, WorkflowStatusResponse } from "@/lib/types";

export function severityBadgeVariant(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return "error";
  if (severity === "action_required" || severity === "warning") return "warning";
  return severity === "success" ? "success" : "info";
}

export function severityIcon(severity: WorkflowEventSeverity) {
  if (severity === "blocked") return ShieldAlert;
  if (severity === "action_required" || severity === "warning") return CircleAlert;
  return severity === "success" ? CircleCheck : CheckCircle2;
}

export function workflowEventCardClass(event: WorkflowEventResponse) {
  return cx(
    "rounded-md border p-3 text-sm",
    event.severity === "blocked" && "border-status-error bg-status-error-muted",
    event.severity === "action_required" && "border-status-warning bg-status-warning-muted",
    event.severity !== "blocked" && event.severity !== "action_required" && "border-border bg-surface-card",
  );
}

export const labelFromSnake = (value: string) => value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const sentenceFromSnake = (value: string) => value.replace(/_/g, " ");
export const formatEventTime = (value: string) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
export const routineEvents = (events: WorkflowEventResponse[]) => events.filter((e) => e.severity !== "blocked" && e.severity !== "action_required");

export function nextActionLabel(status: WorkflowStatusResponse) {
  if (status.next_action.label) return status.next_action.label;
  const map: Record<string, string> = { upload: "Upload statements", review_required: "Review required", resolve_blocker: "Resolve blocker", open_report: "Open report package", wait: "View processing" };
  return map[status.next_action.type] ?? "Open workflow";
}

const WORKFLOW_JARGON_REPLACEMENTS: Array<[RegExp, string]> = [
  [/Package section invariant failed:\s*opening_balance_missing,\s*cash_balance_input_missing,\s*cash_identity_missing/gi, "Upload a bank statement to verify opening and ending cash balances."],
  [/Package section invariant failed:\s*opening_balance_missing/gi, "Opening balance awaits bank statement verification."],
  [/Package section invariant failed:\s*cash_balance_input_missing/gi, "Ending cash balance awaits bank statement verification."],
  [/Package section invariant failed:\s*cash_identity_missing/gi, "Cash account balance awaits bank statement verification."],
  [/Package section invariant failed/gi, "Statement balance check needed"],
  [/\binvariants\b/gi, "checks"],
  [/\binvariant\b/gi, "check"],
  [/\brollforward\b/gi, "continuity"],
  [/\bleakage\b/gi, "unmatched transfers"],
];

export function humanizeWorkflowText(value?: string | null): string {
  if (!value) return "";
  const replaced = WORKFLOW_JARGON_REPLACEMENTS.reduce((acc, [pat, rep]) => acc.replace(pat, rep), value);
  return replaced
    .replace(/\b([a-z]+_[a-z_]+)\b/gi, (match) => match.replace(/_/g, " "))
    .replace(
      /(\d+)((?:\s+[A-Za-z-]+)*\s+)([A-Za-z-]+)\(s\)/g,
      (_match, count: string, middle: string, word: string) =>
        Number(count) === 1 ? `${count}${middle}${word}` : `${count}${middle}${word}s`,
    )
    .replace(/([A-Za-z-]+)\(s\)/g, (_match, word: string) => `${word}s`);
}

export const nextActionSummary = (status: WorkflowStatusResponse) => humanizeWorkflowText(status.next_action.summary);

export function workflowStateCopy(status: WorkflowStatusResponse) {
  const map: Record<string, string> = {
    blocked: "A blocker is holding report readiness.",
    needs_action: "Review the required action so automation can continue.",
    processing: "Automation is processing uploaded source files.",
    ready: "Reports are ready to inspect.",
  };
  return map[status.primary_state] ?? "Upload files to start the automated reporting workflow.";
}

export function fallbackSession(events: WorkflowEventResponse[]): WorkflowSessionSummaryResponse {
  return {
    id: "legacy-workflow-session", status: "active", title: "Workflow session", summary: "Legacy workflow events without a stored session.",
    started_at: events[events.length - 1]?.occurred_at ?? new Date().toISOString(), last_event_at: events[0]?.occurred_at ?? null, source_count: events.length,
    primary_state: events.some((e) => e.severity === "blocked") ? "blocked" : events.some((e) => e.severity === "action_required") ? "needs_action" : events.length ? "processing" : "empty",
    report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
    event_counts: { unread: events.filter((e) => e.status === "unread").length, action_required: events.filter((e) => e.severity === "action_required").length, blocked: events.filter((e) => e.severity === "blocked").length },
  };
}

export function groupEventsBySession(events: WorkflowEventResponse[], sessions: WorkflowSessionSummaryResponse[]) {
  const sessionById = new Map(sessions.map((s) => [s.id, s]));
  const grouped = new Map<string, WorkflowEventResponse[]>();
  for (const event of events) {
    const sid = event.session_id ?? "legacy-workflow-session";
    grouped.set(sid, [...(grouped.get(sid) ?? []), event]);
  }
  return Array.from(grouped.entries()).map(([sid, sessionEvents]) => ({
    session: sessionById.get(sid) ?? fallbackSession(sessionEvents),
    events: sessionEvents.sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)),
  }));
}
