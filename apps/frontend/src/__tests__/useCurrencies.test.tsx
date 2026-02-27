import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCurrencies } from "../hooks/useCurrencies";
import * as api from "../lib/api";

vi.mock("../lib/api", () => ({
    apiFetch: vi.fn(),
}));

describe("useCurrencies", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC16.9.1 returns default currencies while loading", () => {
        vi.mocked(api.apiFetch).mockReturnValue(new Promise(() => {}));

        const { result } = renderHook(() => useCurrencies());

        expect(result.current.loading).toBe(true);
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });

    it("AC16.9.2 updates currencies from API response", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(["SGD", "USD", "EUR", "GBP"]);

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR", "GBP"]);
    });

    it("AC16.9.3 falls back to defaults when API returns empty array", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue([]);

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });

    it("AC16.9.3 falls back to defaults on API error", async () => {
        vi.mocked(api.apiFetch).mockRejectedValue(new Error("network error"));

        const { result } = renderHook(() => useCurrencies());

        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.currencies).toEqual(["SGD", "USD", "EUR"]);
    });
});
