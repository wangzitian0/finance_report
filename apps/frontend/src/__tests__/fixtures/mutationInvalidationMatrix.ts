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
 *
 * The app query client adds a rule on top of this matrix (#2583 S4): after EVERY
 * successful mutation it marks the ledger-derived reads stale
 * (`LEDGER_DERIVED_QUERY_KEYS` in `lib/queryClient.ts`), because Home, /audit
 * and the report pages keep those reads in the cache for one minute. A row with an
 * empty `invalidates` list relies on that rule.
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
    file: "components/settings/SettingsPanels.tsx",
    invalidates: [["accounts"]],
  },
  {
    flow: "statements.review.approve",
    file: "app/(main)/statements/[id]/page.tsx",
    invalidates: [["statement-review"], ["pending-statements"]],
  },
  {
    flow: "statements.review.reject",
    file: "app/(main)/statements/[id]/page.tsx",
    invalidates: [["statement-review"], ["pending-statements"]],
  },
  {
    flow: "statements.review.resolve-conflicts",
    file: "app/(main)/statements/[id]/page.tsx",
    invalidates: [["statement-conflicts"]],
  },
  {
    flow: "statements.review.confirm-envelope",
    file: "app/(main)/statements/[id]/page.tsx",
    invalidates: [["statement-review"]],
  },
  {
    flow: "statements.review.create-custody-account",
    file: "app/(main)/statements/[id]/page.tsx",
    invalidates: [["statement-review-custody-accounts"]],
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
    file: "components/portfolio/Holdings.tsx",
    invalidates: [],
    noInvalidationReason:
      "Cache refresh is delegated to the caller's onSuccess prop — the " +
      "embedding page owns which of its queries a price update refreshes.",
  },
  {
    flow: "workflow.event-lifecycle",
    file: "hooks/useWorkflowStatus.ts",
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
        "(src/__tests__/fixtures/mutationInvalidationMatrix.ts) — declare it before testing it",
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
