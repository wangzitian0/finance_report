// #1827 G-core-hook-tested — direct tests for the shared data hook.
//
// useApiQuery is the core read seam between react-query and the API layer;
// until #1827 it had zero direct test references (98% line coverage included
// it only incidentally). These tests run REAL react-query (only the network
// fn apiFetch is mocked) and pin the hook's contract: path fetching, error
// propagation, option passthrough, and per-key caching.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApiQuery } from "@/hooks/useApiQuery";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

function createSharedClientWrapper() {
  // Mirrors the app's real Providers defaults (staleTime 60s): a second
  // observer mounting within staleTime reads the cache instead of refetching.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

describe("useApiQuery (#1827 G-core-hook-tested)", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("AC-testing.fe-async.1 fetches the given path through apiFetch and exposes the data", async () => {
    mockedApiFetch.mockResolvedValue({ items: [], total: 0 });

    const { result } = renderHook(() =>
      useApiQuery<{ items: unknown[]; total: number }>(["accounts"], "/api/accounts"),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ items: [], total: 0 });
    expect(mockedApiFetch).toHaveBeenCalledTimes(1);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/accounts");
  });

  it("AC-testing.fe-async.1 surfaces apiFetch failures as the query error", async () => {
    mockedApiFetch.mockRejectedValue(new Error("upstream 500"));

    const { result } = renderHook(() => useApiQuery(["failing"], "/api/failing"));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("upstream 500");
    expect(result.current.data).toBeUndefined();
  });

  it("AC-testing.fe-async.1 respects enabled=false and never touches the network", async () => {
    const { result } = renderHook(() =>
      useApiQuery(["disabled"], "/api/disabled", { enabled: false }),
    );

    // fetchStatus settles to idle for a disabled query; no fetch may happen.
    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(result.current.isPending).toBe(true);
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("AC-testing.fe-async.1 passes query options through (select transform)", async () => {
    mockedApiFetch.mockResolvedValue({ items: [1, 2, 3], total: 3 });

    const { result } = renderHook(() =>
      useApiQuery<{ items: number[]; total: number }>(["with-select"], "/api/with-select", {
        select: (data) => data.total,
      } as never),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBe(3);
  });

  it("AC-testing.fe-async.1 shares one fetch per query key within a client", async () => {
    mockedApiFetch.mockResolvedValue({ value: 42 });
    const { wrapper } = createSharedClientWrapper();

    const first = renderHook(() => useApiQuery(["shared", "key"], "/api/shared"), {
      wrapper,
    });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));

    const second = renderHook(() => useApiQuery(["shared", "key"], "/api/shared"), {
      wrapper,
    });
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));

    // The second subscriber reads the cached entry — one network call total.
    expect(second.result.current.data).toEqual({ value: 42 });
    expect(mockedApiFetch).toHaveBeenCalledTimes(1);

    // A different key is a different cache entry and fetches again.
    const third = renderHook(() => useApiQuery(["shared", "other"], "/api/shared-other"), {
      wrapper,
    });
    await waitFor(() => expect(third.result.current.isSuccess).toBe(true));
    expect(mockedApiFetch).toHaveBeenCalledTimes(2);
  });
});
