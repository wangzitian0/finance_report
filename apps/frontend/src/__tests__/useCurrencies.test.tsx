import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCurrencies } from "../hooks/useCurrencies";
import { apiOperation } from "../lib/api-client";

vi.mock("../lib/api-client", () => ({
    apiOperation: vi.fn(),
}));

describe("useCurrencies", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    // AC-pricing.fe-currencies.1
    it("AC16.9.1 returns default currencies while loading", () => {
        vi.mocked(apiOperation).mockReturnValue(new Promise(() => {}));

        const { result } = renderHook(() => useCurrencies());

        expect(result.current.loading).toBe(true);
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });

    // AC-pricing.fe-currencies.2
    it("AC16.9.2 updates currencies from API response", async () => {
        vi.mocked(apiOperation).mockResolvedValue(["SGD", "USD", "EUR", "GBP"] as any);

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR", "GBP"]);
    });

    // AC-pricing.fe-currencies.3
    it("AC16.9.3 falls back to defaults when API returns empty array", async () => {
        vi.mocked(apiOperation).mockResolvedValue([] as any);

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });

    it("AC16.9.3 falls back to defaults on API error", async () => {
        vi.mocked(apiOperation).mockRejectedValue(new Error("network error"));

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });
});
