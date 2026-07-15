"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApiQuery } from "@/hooks/useApiQuery";
import { updateWorkflowEventStatus } from "@/lib/api";
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

export function isWorkflowStatusResponse(value: unknown): value is WorkflowStatusResponse {
  if (!value || typeof value !== "object") return false;
  const status = value as Partial<WorkflowStatusResponse>;
  return Boolean(status.primary_state && status.next_action && status.report_readiness && status.event_counts);
}

export function useWorkflowStatusQuery() {
  return useApiQuery<WorkflowStatusResponse>(WORKFLOW_STATUS_QUERY_KEY, "/api/workflow/status", {
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  });
}

export function useWorkflowEventsQuery(limit: number, scope: string, enabled = true) {
  return useApiQuery<WorkflowEventListResponse>(
    [...WORKFLOW_EVENTS_QUERY_KEY, scope, limit],
    `/api/workflow/events?limit=${limit}`,
    { enabled },
  );
}

export function useWorkflowLifecycleMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, status }: { eventId: string; status: WorkflowEventStatus }) =>
      updateWorkflowEventStatus(eventId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WORKFLOW_STATUS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: WORKFLOW_EVENTS_QUERY_KEY });
    },
  });
}
