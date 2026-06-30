"use client";

import { BackLink } from "@/components/ui/BackLink";

// EPIC-022 AC22.21.3: the Audit hub's deep pages (journal, reconciliation,
// confidence, processing) are reached from /audit, so they offer a back-link to
// it. Users who deep-linked in from the attention inbox are still returned to
// /attention (BackLink handles the attention-origin override).
export function AuditBackLink() {
    return <BackLink href="/audit">Back to Audit</BackLink>;
}
