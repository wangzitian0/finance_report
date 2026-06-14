"use client";

import { Stage2ReviewQueue } from "@/components/review/Stage2ReviewQueue";

/**
 * Dedicated Stage-2 review surface (#1001).
 *
 * Canonical, top-level home for the reconciliation review queue. Previously the
 * only entry was `/reconciliation/review-queue`, which nested review under the
 * reconciliation module ("parasitic on statements"). This route makes Stage-2
 * review a first-class destination reached from the Attention center, decoupled
 * from the reconciliation workbench. The run-scoped variant lives at
 * `/review/run/[runId]`.
 */
export default function ReviewPage() {
    return <Stage2ReviewQueue />;
}
