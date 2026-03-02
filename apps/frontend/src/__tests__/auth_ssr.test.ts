import { afterEach, describe, it, expect, vi } from "vitest";

describe("auth utilities SSR", () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("returns null for all getters when window is undefined", async () => {
        vi.stubGlobal("window", undefined);
        
        const { getUserId, getUserEmail, getAccessToken, isAuthenticated } = await import("../lib/auth");
        
        expect(getUserId()).toBeNull();
        expect(getUserEmail()).toBeNull();
        expect(getAccessToken()).toBeNull();
        expect(isAuthenticated()).toBe(false);
    });
});
