import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useBaseCurrency } from "../hooks/useBaseCurrency";
import * as api from "../lib/api";

vi.mock("../lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("useBaseCurrency (#1487)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults to SGD while loading", () => {
    vi.mocked(api.apiFetch).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useBaseCurrency());

    expect(result.current.loading).toBe(true);
    expect(result.current.baseCurrency).toBe("SGD");
  });

  it("returns the configured base currency from app config", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({ base_currency: "HKD" });

    const { result } = renderHook(() => useBaseCurrency());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.baseCurrency).toBe("HKD");
  });

  it("falls back to SGD on API error", async () => {
    vi.mocked(api.apiFetch).mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useBaseCurrency());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.baseCurrency).toBe("SGD");
  });
});
