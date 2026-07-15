"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";

import { Alert, Badge } from "@/components/ui";
import {
  useWorkflowEventsQuery,
  useWorkflowLifecycleMutation,
  useWorkflowStatusQuery,
} from "@/hooks/useWorkflowStatus";

import { WorkflowInbox } from "./WorkflowInbox";
import { WorkflowStatusFeed } from "./WorkflowStatusFeed";

/**
 * Full-page workflow events surface (was inline in
 * components/workflow/WorkflowNotifications.tsx, #1868 S5 PR-C).
 */

export function WorkflowEventsPageContent() {
  const statusQuery = useWorkflowStatusQuery();
  const eventsQuery = useWorkflowEventsQuery(100, "page");
  const lifecycleMutation = useWorkflowLifecycleMutation();

  return (
    <div className="p-6">
      <div className="page-header flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="page-title">Notifications</h1>
          <p className="page-description">Your action center — everything that needs your review across uploads, reconciliation, and reports.</p>
        </div>
        <Link href="/upload" className="btn-primary inline-flex justify-center text-sm">
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
