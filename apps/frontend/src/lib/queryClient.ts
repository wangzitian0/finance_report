import { MutationCache, QueryClient, type QueryKey } from "@tanstack/react-query";

import { SHARED_STALE_MS } from "@/lib/sharedQueries";

/**
 * Query-key prefixes that hold data derived from the ledger (#2583 S4).
 *
 * Home, /audit and the report pages keep these reads in the cache for `SHARED_STALE_MS`.
 * A successful mutation can change them, so `createAppQueryClient` marks them stale after every
 * successful mutation. Active queries refetch at once. Inactive queries refetch on the next mount.
 */
export const LEDGER_DERIVED_QUERY_KEYS: readonly QueryKey[] = [
  ["statements"],
  ["reconciliation"],
  ["accounts"],
  ["dashboard"],
  ["report"],
  ["report-package"],
  ["workflow"],
  // The advisor brief reads the report readiness, so a ledger change can outdate it.
  ["chat", "suggestions"],
];

/** True for a read of `/portfolio`: its key starts with a "portfolio-" element (#2648). */
function isPortfolioQueryKey(queryKey: QueryKey): boolean {
  const head = queryKey[0];
  return typeof head === "string" && head.startsWith("portfolio-");
}

/**
 * Mark the reads of `/portfolio` stale, for example `["portfolio-holdings", ...]` and
 * `["portfolio-summary", ...]` (#2648). A successful brokerage import changes them. They are not
 * ledger-derived prefixes: each read has its own first key element.
 */
export function invalidatePortfolioQueries(client: QueryClient): Promise<void> {
  return client.invalidateQueries({ predicate: (query) => isPortfolioQueryKey(query.queryKey) });
}

export function invalidateLedgerDerivedQueries(client: QueryClient): Promise<unknown> {
  return Promise.all(
    LEDGER_DERIVED_QUERY_KEYS.map((queryKey) => client.invalidateQueries({ queryKey })),
  );
}

export function createAppQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    mutationCache: new MutationCache({
      onSuccess: () => {
        void invalidateLedgerDerivedQueries(client);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: SHARED_STALE_MS,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
  return client;
}
