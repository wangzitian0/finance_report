import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useBaseCurrency } from "../hooks/useBaseCurrency";
import { apiOperation } from "../lib/api-client";

vi.mock("../lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

describe("useBaseCurrency (#1487)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults to SGD while loading", () => {
    vi.mocked(apiOperation).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useBaseCurrency());

    expect(result.current.loading).toBe(true);
    expect(result.current.baseCurrency).toBe("SGD");
  });

  it("returns the configured base currency from app config", async () => {
    vi.mocked(apiOperation).mockResolvedValue({ base_currency: "HKD" } as any);

    const { result } = renderHook(() => useBaseCurrency());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.baseCurrency).toBe("HKD");
  });

  it("falls back to SGD on API error", async () => {
    vi.mocked(apiOperation).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useBaseCurrency());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.baseCurrency).toBe("SGD");
  });
});
