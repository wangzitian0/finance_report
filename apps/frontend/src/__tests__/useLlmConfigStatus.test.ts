import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { fetchLlmConfigStatus } from "@/lib/api";
import { setUser } from "@/lib/auth";

vi.mock("@/lib/api", () => ({
  fetchLlmConfigStatus: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchLlmConfigStatus);

beforeEach(() => {
  localStorage.clear();
  mockedFetch.mockReset();
});

describe("useLlmConfigStatus (EPIC-023 PR4)", () => {
  it("does not fetch when there is no local session", async () => {
    const { result } = renderHook(() => useLlmConfigStatus());
    expect(mockedFetch).not.toHaveBeenCalled();
    expect(result.current.configured).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("fetches the status on mount when a session exists", async () => {
    setUser("u1", "u@example.com");
    mockedFetch.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(false));
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
  });

  it("exposes configured=true when the backend reports a usable config", async () => {
    setUser("u1", "u@example.com");
    mockedFetch.mockResolvedValue({ configured: true });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(true));
  });

  it("leaves configured untouched when the fetch fails", async () => {
    setUser("u1", "u@example.com");
    mockedFetch.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.configured).toBeNull();
  });

  it("refresh re-fetches the status on demand", async () => {
    setUser("u1", "u@example.com");
    mockedFetch.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());
    await waitFor(() => expect(result.current.configured).toBe(false));

    mockedFetch.mockResolvedValue({ configured: true });
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.configured).toBe(true);
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });
});
