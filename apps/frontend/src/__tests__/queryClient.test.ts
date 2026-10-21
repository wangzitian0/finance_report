// #2583 S4 — cache invalidation after a mutation.
//
// Home, /attention and the report pages keep ledger-derived reads in the cache for one minute.
// A successful mutation can change them, so the app client marks them stale. These tests drive a
// real QueryClient from `createAppQueryClient`; only the mutation function is a stub.

import { MutationObserver } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import {
  LEDGER_DERIVED_QUERY_KEYS,
  createAppQueryClient,
} from "@/lib/queryClient";

const PROBE = "__probe__";

describe("app query client (#2583 S4)", () => {
  // AC-reporting.fe-fetch-budget.4
  it("AC-reporting.fe-fetch-budget.4 marks every ledger-derived read stale after a successful mutation", async () => {
    const client = createAppQueryClient();
    const seeded = LEDGER_DERIVED_QUERY_KEYS.map((key) => [...key, PROBE]);
    // An empty list would make the loop below assert nothing.
    expect(seeded.length).toBeGreaterThanOrEqual(8);
    for (const key of seeded) client.setQueryData(key, { probe: true });
    const unrelated = ["settings", "profile", PROBE];
    client.setQueryData(unrelated, { probe: true });

    await new MutationObserver(client, { mutationFn: async () => "ok" }).mutate();

    for (const key of seeded) {
      expect(client.getQueryState(key)?.isInvalidated, `${JSON.stringify(key)} stayed fresh`).toBe(true);
    }
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
  });

  // AC-reporting.fe-fetch-budget.4
  it("AC-reporting.fe-fetch-budget.4 keeps the cache after a failed mutation", async () => {
    const client = createAppQueryClient();
    const key = ["report", "balance-sheet", PROBE];
    client.setQueryData(key, { probe: true });

    await expect(
      new MutationObserver(client, {
        mutationFn: async () => {
          throw new Error("rejected");
        },
      }).mutate(),
    ).rejects.toThrow("rejected");

    expect(client.getQueryState(key)?.isInvalidated).toBe(false);
  });

  // AC-reporting.fe-fetch-budget.4
  it("AC-reporting.fe-fetch-budget.4 invalidation covers the keys that the Home, Attention and report routes use", () => {
    const prefixes = LEDGER_DERIVED_QUERY_KEYS.map((key) => key[0]);
    expect(prefixes).toEqual(
      expect.arrayContaining([
        "statements",
        "reconciliation",
        "accounts",
        "dashboard",
        "report",
        "report-package",
        "workflow",
        "chat",
      ]),
    );
  });
});
