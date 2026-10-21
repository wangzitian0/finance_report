"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApiQuery } from "@/hooks/useApiQuery";
import { apiOperation } from "@/lib/api-client";
import type {
  WorkflowEventListResponse,
  WorkflowEventStatus,
  WorkflowStatusResponse,
} from "@/lib/types";

/**
 * Workflow status/events data hooks (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export const WORKFLOW_STATUS_QUERY_KEY = ["workflow", "status"] as const;
export const WORKFLOW_EVENTS_QUERY_KEY = ["workflow", "events"] as const;

export function isWorkflowStatusResponse(
  value: unknown,
): value is WorkflowStatusResponse {
  if (!value || typeof value !== "object") return false;
  const status = value as Partial<WorkflowStatusResponse>;
  return Boolean(
    status.primary_state &&
    status.next_action &&
    status.report_readiness &&
    status.event_counts,
  );
}

/** Poll interval while the status shows pending work. */
export const WORKFLOW_STATUS_POLL_PENDING_MS = 30_000;
/** Poll interval while nothing is pending. */
export const WORKFLOW_STATUS_POLL_IDLE_MS = 120_000;

/**
 * True when the user can still see work move: an active session, a parsing source, an
 * action-required or blocked state, or an open action-required or blocked event.
 * A missing or malformed status counts as pending, so a failed read retries at the fast pace
 * and the interval callback never throws on a payload without the expected fields.
 */
export function workflowStatusHasPendingWork(
  status: WorkflowStatusResponse | undefined,
): boolean {
  if (!isWorkflowStatusResponse(status)) return true;
  return (
    Boolean(status.active_session) ||
    status.primary_state === "processing" ||
    status.primary_state === "needs_action" ||
    status.primary_state === "blocked" ||
    status.event_counts.action_required > 0 ||
    status.event_counts.blocked > 0
  );
}

/**
 * The shell mounts this query on every page. Each read costs the server a full readiness
 * check, so the poll runs every 30 s only while work is pending, and every 120 s otherwise.
 * A focus refetch still gives a fresh status when the user returns to the tab.
 */
export function useWorkflowStatusQuery() {
  return useApiQuery(
    WORKFLOW_STATUS_QUERY_KEY,
    "get_workflow_status_endpoint_workflow_status_get",
    {},
    {
      refetchInterval: (query) =>
        workflowStatusHasPendingWork(query.state.data)
          ? WORKFLOW_STATUS_POLL_PENDING_MS
          : WORKFLOW_STATUS_POLL_IDLE_MS,
      refetchOnWindowFocus: true,
    },
  );
}

export function useWorkflowEventsQuery(
  limit: number,
  scope: string,
  enabled = true,
) {
  return useApiQuery(
    [...WORKFLOW_EVENTS_QUERY_KEY, scope, limit],
    "list_workflow_events_endpoint_workflow_events_get",
    { query: { limit } },
    { enabled },
  );
}

export function useWorkflowLifecycleMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      eventId,
      status,
    }: {
      eventId: string;
      status: WorkflowEventStatus;
    }) =>
      apiOperation(
        "update_workflow_event_status_endpoint_workflow_events__event_id__patch",
        {
          path: { event_id: eventId },
          body: { status },
        },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: WORKFLOW_STATUS_QUERY_KEY,
      });
      void queryClient.invalidateQueries({
        queryKey: WORKFLOW_EVENTS_QUERY_KEY,
      });
    },
  });
}
