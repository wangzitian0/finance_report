// #1827 G-core-hook-tested — direct tests for the shared data hook.
//
// useApiQuery is the core read seam between react-query and the API layer;
// until #1827 it had zero direct test references (98% line coverage included
// it only incidentally). These tests run REAL react-query (only the network
// fn apiOperation is mocked) and pin the hook's contract: operation fetching, error
// propagation, option passthrough, and per-key caching.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApiQuery } from "@/hooks/useApiQuery";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

const mockedApiOperation = vi.mocked(apiOperation);
const operationId = "list_accounts_accounts_get" as const;

function createSharedClientWrapper() {
  // Mirrors the app's real Providers defaults (staleTime 60s): a second
  // observer mounting within staleTime reads the cache instead of refetching.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  return { client, wrapper: Wrapper };
}

describe("useApiQuery (#1827 G-core-hook-tested)", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
  });

  it("AC-testing.fe-async.1 fetches the given operation through apiOperation and exposes the data", async () => {
    mockedApiOperation.mockResolvedValue({ items: [], total: 0 });

    const { result } = renderHook(() =>
      useApiQuery(["examples"], operationId, {}),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ items: [], total: 0 });
    expect(mockedApiOperation).toHaveBeenCalledTimes(1);
    expect(mockedApiOperation).toHaveBeenCalledWith(operationId, {});
  });

  it("AC-testing.fe-async.1 surfaces apiOperation failures as the query error", async () => {
    mockedApiOperation.mockRejectedValue(new Error("upstream 500"));

    const { result } = renderHook(() =>
      useApiQuery(["failing"], operationId, {}),
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("upstream 500");
    expect(result.current.data).toBeUndefined();
  });

  it("AC-testing.fe-async.1 respects enabled=false and never touches the network", async () => {
    const { result } = renderHook(() =>
      useApiQuery(["disabled"], operationId, {}, { enabled: false }),
    );

    // fetchStatus settles to idle for a disabled query; no fetch may happen.
    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(result.current.isPending).toBe(true);
    expect(mockedApiOperation).not.toHaveBeenCalled();
  });

  it("AC-testing.fe-async.1 passes query options through (select transform)", async () => {
    mockedApiOperation.mockResolvedValue({ items: [], total: 3 });

    const { result } = renderHook(() =>
      useApiQuery(
        ["with-select"],
        operationId,
        {},
        {
          select: (data) => data.total,
        },
      ),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBe(3);
  });

  it("AC-testing.fe-async.1 shares one fetch per query key within a client", async () => {
    mockedApiOperation.mockResolvedValue({ items: [], total: 42 });
    const { wrapper } = createSharedClientWrapper();

    const first = renderHook(
      () => useApiQuery(["shared", "key"], operationId, {}),
      {
        wrapper,
      },
    );
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));

    const second = renderHook(
      () => useApiQuery(["shared", "key"], operationId, {}),
      {
        wrapper,
      },
    );
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));

    // The second subscriber reads the cached entry — one network call total.
    expect(second.result.current.data).toEqual({ items: [], total: 42 });
    expect(mockedApiOperation).toHaveBeenCalledTimes(1);

    // A different key is a different cache entry and fetches again.
    const third = renderHook(
      () => useApiQuery(["shared", "other"], operationId, {}),
      {
        wrapper,
      },
    );
    await waitFor(() => expect(third.result.current.isSuccess).toBe(true));
    expect(mockedApiOperation).toHaveBeenCalledTimes(2);
  });
});
