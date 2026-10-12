import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { apiOperation } from "@/lib/api-client";
import { setUser } from "@/lib/auth";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

const mockedApiOperation = vi.mocked(apiOperation);

beforeEach(() => {
  localStorage.clear();
  mockedApiOperation.mockReset();
});

describe("useLlmConfigStatus (EPIC-023 PR4, #1868 S5 PR-C: useApiQuery migration)", () => {
  it("does not fetch when there is no local session", async () => {
    const { result } = renderHook(() => useLlmConfigStatus());
    expect(mockedApiOperation).not.toHaveBeenCalled();
    expect(result.current.configured).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("fetches the status on mount when a session exists", async () => {
    setUser("u1", "u@example.com");
    mockedApiOperation.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(false));
    expect(mockedApiOperation).toHaveBeenCalledTimes(1);
    expect(mockedApiOperation).toHaveBeenCalledWith("get_config_status_llm_config_status_get", expect.anything());
    expect(result.current.loading).toBe(false);
  });

  it("exposes configured=true when the backend reports a usable config", async () => {
    setUser("u1", "u@example.com");
    mockedApiOperation.mockResolvedValue({ configured: true });

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(result.current.configured).toBe(true));
  });

  it("leaves configured untouched when the fetch fails", async () => {
    setUser("u1", "u@example.com");
    mockedApiOperation.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useLlmConfigStatus());

    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.configured).toBeNull();
  });

  it("refresh re-fetches the status on demand", async () => {
    setUser("u1", "u@example.com");
    mockedApiOperation.mockResolvedValue({ configured: false });

    const { result } = renderHook(() => useLlmConfigStatus());
    await waitFor(() => expect(result.current.configured).toBe(false));

    mockedApiOperation.mockResolvedValue({ configured: true });
    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(result.current.configured).toBe(true));
    expect(mockedApiOperation).toHaveBeenCalledTimes(2);
  });
});
