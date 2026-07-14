// Real-QueryClient invalidation probe (#1827 G-async-seam).
//
// Per-flow tests render the REAL component with this probe's QueryClient,
// drive the mutating flow (only the network fn `apiFetch` is mocked — react
// query itself runs for real), then assert the query keys DECLARED in
// MUTATION_INVALIDATION_MATRIX actually became invalidated. The probe seeds a
// passive (never observed) query under each declared prefix, so react-query's
// fuzzy matching must reach it and no refetch can race the assertion back to
// fresh.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { expect } from "vitest";

import { declaredInvalidations } from "@/lib/queryInvalidation";

export const PROBE_SUFFIX = "__invalidation_probe__";

export function createInvalidationProbe(
  flow: string,
  dynamicSuffix: readonly unknown[] = [],
) {
  const declared = declaredInvalidations(flow);
  if (declared.length === 0) {
    throw new Error(
      `flow '${flow}' declares no invalidations — there is nothing to probe`,
    );
  }

  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const seededKeys = declared.map((key) => [...key, ...dynamicSuffix, PROBE_SUFFIX]);
  for (const key of seededKeys) {
    client.setQueryData(key, { probe: true });
  }

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  return {
    client,
    wrapper: Wrapper,
    /** Assert every declared key prefix was invalidated by the flow. */
    expectDeclaredInvalidated() {
      for (const key of seededKeys) {
        expect(
          client.getQueryState(key)?.isInvalidated,
          `flow '${flow}' must invalidate ${JSON.stringify(key)} ` +
            "(declared in MUTATION_INVALIDATION_MATRIX)",
        ).toBe(true);
      }
    },
    /** Assert nothing was invalidated (pre-flow sanity in tests). */
    expectNothingInvalidated() {
      for (const key of seededKeys) {
        expect(client.getQueryState(key)?.isInvalidated).toBe(false);
      }
    },
  };
}
