/**
 * Barrel re-export — the workflow notification surfaces used to live inline
 * in this file (769 lines); split into focused files under
 * components/workflow/ (#1868 S5 PR-C, G-no-godfile). Kept as a barrel so
 * existing `@/components/workflow/WorkflowNotifications` imports keep
 * resolving unchanged.
 */

export { UploadToReportHome, UploadToReportHomePanel } from "./UploadToReportHome";
export {
  WorkflowEventsPageContent,
  WorkflowStatusFeed,
  type WorkflowStatusFeedProps,
} from "./WorkflowEventsPageContent";
export { WorkflowInbox, WorkflowEventCard } from "./WorkflowInbox";
export { WorkflowNotificationCenter } from "./WorkflowNotificationCenter";
