import { render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("Home fetch budget", () => {
  beforeEach(() => { api.mockReset(); X.mockApiMap(api, X.makeHomeRoutes(), null); setTestUrl("/"); });

  it("mounts deduped, warm cache, filter refetches", async () => {
    const w = X.clientWrapper(X.createStaleClient()), first = R(<HomePage />, { wrapper: w });
    await X.settleHomeBudget(api);
    const counts = new Map<string, number>();
    for (const k of X.homeCallKeys(api)) counts.set(k, (counts.get(k) ?? 0) + 1);
    E([...counts].filter(([, c]) => c > 1)).toEqual([]);
    E([...counts.keys()].map((k) => k.split(" ")[0]).sort()).toEqual(X.HOME_EXPECTED_OPS);

    first.unmount(); api.mockClear();
    const second = R(<HomePage />, { wrapper: w });
    await W(() => E(S.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"));
    E(X.homeCallKeys(api).filter((k) => !k.startsWith(X.OPS.WF))).toEqual([]);
    await X.runHomeBudgetMutations(api); second.unmount();
  });

  it("streams cards & caches suggestions 5m", async () => {
    let resolveSug!: (v: unknown) => void;
    X.mockApiMap(api, X.makeHomeRoutes({ [X.OPS.CF]: () => new Promise(() => undefined), [X.OPS.SUG]: () => new Promise((r) => { resolveSug = r; }) }), null);
    const client = X.createStaleClient(); R(<HomePage />, { wrapper: X.clientWrapper(client) });
    await W(() => E(S.getByText("Net worth").nextElementSibling).toHaveTextContent("$4,000"));
    await W(() => E(S.getByText("Net income").nextElementSibling).toHaveTextContent("+$2,300"));
    E(S.getByTestId("cockpit-card-cash-flow")).toHaveTextContent("Loading…");
    const sug = client.getQueryCache().getAll().filter((q) => JSON.stringify(q.queryKey).includes("suggestions"));
    E(sug).toHaveLength(1); E(sug[0].observers[0]?.options.staleTime).toBeGreaterThanOrEqual(5 * 60 * 1000);
    resolveSug({ suggestions: [], structured_suggestions: [] });
  });
});
