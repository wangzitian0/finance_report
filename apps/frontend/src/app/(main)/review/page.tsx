"use client";

import { Stage2ReviewQueue } from "@/components/review/Stage2ReviewQueue";

/**
 * Dedicated Stage-2 review surface (#1001).
 *
 * NOTE (EPIC-022 / AC22.2.4): `/review` is permanently redirected to `/notifications`
 * in next.config.mjs. The primary first-class route for Stage-2 review queue is
 * mounted at `/reconciliation/review-queue`, while the run-scoped review lives at
 * `/review/run/[runId]`. This component is retained for test harness and fallback.
 */
export default function ReviewPage() {
    return <Stage2ReviewQueue />;
}
