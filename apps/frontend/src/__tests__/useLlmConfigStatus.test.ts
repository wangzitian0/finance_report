import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { apiFetch } from "@/lib/api";
import { setUser } from "@/lib/auth";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  localStorage.clear();
  mockedApiFetch.mockReset();
});

describe("useLlmConfigStatus (EPIC-023 PR4, #1868 S5 PR-C: useApiQuery migration)", () => {
  it("does not fetch when there is no local session", async () => {
    const { result } = renderHook(() => useLlmConfigStatus());
    expect(mockedApiFetch).not.toHaveBeenCalled();
    expect(result.current.configured).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("fetches the status on mount when a session exists", async () => {
    setUser("u1", "u@example.com");
    mockedApiFetch.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(false));
    expect(mockedApiFetch).toHaveBeenCalledTimes(1);
    expect(mockedApiFetch).toHaveBeenCalledWith("/api/llm/config/status");
    expect(result.current.loading).toBe(false);
  });

  it("exposes configured=true when the backend reports a usable config", async () => {
    setUser("u1", "u@example.com");
    mockedApiFetch.mockResolvedValue({ configured: true });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(true));
  });

  it("leaves configured untouched when the fetch fails", async () => {
    setUser("u1", "u@example.com");
    mockedApiFetch.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.configured).toBeNull();
  });

  it("refresh re-fetches the status on demand", async () => {
    setUser("u1", "u@example.com");
    mockedApiFetch.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());
    await waitFor(() => expect(result.current.configured).toBe(false));

    mockedApiFetch.mockResolvedValue({ configured: true });
    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(result.current.configured).toBe(true));
    expect(mockedApiFetch).toHaveBeenCalledTimes(2);
  });
});
