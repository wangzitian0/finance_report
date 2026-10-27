import { describe, it, expect, beforeEach, vi } from "vitest";
import {
    getUserId,
    getUserEmail,
    setUser,
    clearUser,
    isAuthenticated,
} from "../lib/auth";

const localStorageMock = (() => {
    let store: Record<string, string> = {};
    return {
        getItem: (key: string) => store[key] ?? null,
        setItem: (key: string, value: string) => { store[key] = value; },
        removeItem: (key: string) => { delete store[key]; },
        clear: () => { store = {}; },
    };
})();

vi.stubGlobal("localStorage", localStorageMock);

describe("auth utilities", () => {
    beforeEach(() => {
        localStorageMock.clear();
        vi.restoreAllMocks();
    });

    describe("getUserId", () => {
        // AC-identity.fe-auth.1
        it("AC16.5.1/AC16.5.2 returns null when key is not set", () => {
            expect(getUserId()).toBeNull();
        });

        // AC-identity.fe-auth.2
        it("AC16.5.2 returns stored userId from localStorage", () => {
            localStorage.setItem("finance_user_id", "user-123");
            expect(getUserId()).toBe("user-123");
        });
    });

    describe("getUserEmail", () => {
        it("returns null when key is not set", () => {
            expect(getUserEmail()).toBeNull();
        });

        it("returns stored email from localStorage", () => {
            localStorage.setItem("finance_user_email", "test@example.com");
            expect(getUserEmail()).toBe("test@example.com");
        });
    });

    describe("setUser", () => {
        // AC-identity.fe-auth.3
        it("AC16.5.3 stores userId and email", () => {
            setUser("user-456", "alice@example.com");
            expect(localStorage.getItem("finance_user_id")).toBe("user-456");
            expect(localStorage.getItem("finance_user_email")).toBe("alice@example.com");
        });
    });

    describe("clearUser", () => {
        // AC-identity.fe-auth.4
        it("AC16.5.4 removes all auth keys from localStorage", () => {
            setUser("user-789", "bob@example.com");
            clearUser();
            expect(localStorage.getItem("finance_user_id")).toBeNull();
            expect(localStorage.getItem("finance_user_email")).toBeNull();
        });
    });

    describe("isAuthenticated", () => {
        it("AC16.5.5 returns false when no local session marker is stored", () => {
            expect(isAuthenticated()).toBe(false);
        });

        // AC-identity.fe-auth.5
        it("AC16.5.5 returns true when non-secret user session metadata exists", () => {
            setUser("user-456", "alice@example.com");
            expect(isAuthenticated()).toBe(true);
        });
    });
});
