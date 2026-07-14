/**
 * Mutation → cache-invalidation matrix (#1827 G-async-seam /
 * G-no-undeclared-mutations).
 *
 * Every `useMutation` call site in `src/` MUST have exactly one row here
 * declaring which react-query key prefixes it invalidates on success (or an
 * explicit reason why it invalidates nothing). Two locks enforce the matrix:
 *
 * - `src/__tests__/mutationInvalidationLock.test.ts` enumerates the real
 *   `useMutation` call sites on disk and reds on any file whose call-site
 *   count disagrees with its declared rows — a NEW mutation cannot skip the
 *   matrix by forgetfulness.
 * - Per-flow tests (via `src/__tests__/fixtures/invalidationProbe.tsx`) drive
 *   the REAL component flow against a real QueryClient and assert the
 *   declared keys actually become invalidated — removing an
 *   `invalidateQueries` call reds the flow's test.
 *
 * Keys are STATIC prefixes; react-query's default fuzzy matching extends them
 * to runtime-suffixed keys (e.g. `["statement-conflicts", statementId]`).
 */

import type { QueryKey } from "@tanstack/react-query";

export interface MutationInvalidationRule {
  /** Stable flow id referenced by the per-flow invalidation tests. */
  flow: string;
  /** Source file, relative to `apps/frontend/src`, owning the `useMutation`. */
  file: string;
  /** Static query-key prefixes the flow MUST invalidate on success. */
  invalidates: readonly QueryKey[];
  /** Required when `invalidates` is empty: why no invalidation is needed. */
  noInvalidationReason?: string;
}

export const MUTATION_INVALIDATION_MATRIX: readonly MutationInvalidationRule[] = [
  {
    flow: "accounts.delete",
    file: "app/(main)/accounts/page.tsx",
    invalidates: [["accounts"]],
  },
  {
    flow: "assets.reconcile",
    file: "app/(main)/assets/page.tsx",
    invalidates: [["positions"]],
  },
  {
    flow: "assets.create-valuation",
    file: "app/(main)/assets/page.tsx",
    invalidates: [["valuation-snapshots"]],
  },
  {
    flow: "statements.review.approve",
    file: "app/(main)/statements/[id]/review/page.tsx",
    invalidates: [],
    noInvalidationReason:
      "Navigates to the statement detail (or attention) route on success; " +
      "the review surface unmounts and the destination remounts fresh queries.",
  },
  {
    flow: "statements.review.reject",
    file: "app/(main)/statements/[id]/review/page.tsx",
    invalidates: [],
    noInvalidationReason:
      "Navigates back to /statements on success; the review surface unmounts " +
      "and the list route remounts fresh queries.",
  },
  {
    flow: "statements.review.resolve-conflicts",
    file: "app/(main)/statements/[id]/review/page.tsx",
    invalidates: [["statement-conflicts"]],
  },
  {
    flow: "statements.review.reparse",
    file: "app/(main)/statements/[id]/review/page.tsx",
    invalidates: [],
    noInvalidationReason:
      "Navigates to the statement detail route to watch the re-parse; the " +
      "review surface unmounts and the detail route remounts fresh queries.",
  },
  {
    flow: "reconciliation.run",
    file: "components/reconciliation/Workbench.tsx",
    invalidates: [["reconciliation"]],
  },
  {
    flow: "reconciliation.accept-match",
    file: "components/reconciliation/Workbench.tsx",
    invalidates: [["reconciliation"]],
  },
  {
    flow: "reconciliation.reject-match",
    file: "components/reconciliation/Workbench.tsx",
    invalidates: [["reconciliation"]],
  },
  {
    flow: "reconciliation.batch-accept",
    file: "components/reconciliation/Workbench.tsx",
    invalidates: [["reconciliation"]],
  },
  {
    flow: "portfolio.price-update",
    file: "components/portfolio/PriceUpdateForm.tsx",
    invalidates: [],
    noInvalidationReason:
      "Cache refresh is delegated to the caller's onSuccess prop — the " +
      "embedding page owns which of its queries a price update refreshes.",
  },
  {
    flow: "workflow.event-lifecycle",
    file: "components/workflow/WorkflowNotifications.tsx",
    invalidates: [
      ["workflow", "status"],
      ["workflow", "events"],
    ],
  },
  {
    flow: "assets.guided-evidence-create",
    file: "components/assets/GuidedEvidenceForm.tsx",
    invalidates: [["valuation-snapshots"]],
  },
];

/** The declared invalidation prefixes for one flow; throws on unknown flows. */
export function declaredInvalidations(flow: string): readonly QueryKey[] {
  const rule = MUTATION_INVALIDATION_MATRIX.find((r) => r.flow === flow);
  if (!rule) {
    throw new Error(
      `flow '${flow}' is not declared in MUTATION_INVALIDATION_MATRIX ` +
        "(src/lib/queryInvalidation.ts) — declare it before testing it",
    );
  }
  return rule.invalidates;
}

/** Declared rule count per owning file — the enumeration lock's expectation. */
export function declaredMutationCountByFile(): Map<string, number> {
  const counts = new Map<string, number>();
  for (const rule of MUTATION_INVALIDATION_MATRIX) {
    counts.set(rule.file, (counts.get(rule.file) ?? 0) + 1);
  }
  return counts;
}
