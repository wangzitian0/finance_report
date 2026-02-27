import { describe, it, expect, beforeEach, vi } from "vitest";
import {
    getUserId,
    getUserEmail,
    getAccessToken,
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
        it("AC16.5.2 returns null when key is not set", () => {
            expect(getUserId()).toBeNull();
        });

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

    describe("getAccessToken", () => {
        it("returns null when no token is stored", () => {
            expect(getAccessToken()).toBeNull();
        });

        it("returns stored token from localStorage", () => {
            localStorage.setItem("finance_access_token", "eyJhbGci...");
            expect(getAccessToken()).toBe("eyJhbGci...");
        });
    });

    describe("setUser", () => {
        it("AC16.5.3 stores userId and email", () => {
            setUser("user-456", "alice@example.com");
            expect(localStorage.getItem("finance_user_id")).toBe("user-456");
            expect(localStorage.getItem("finance_user_email")).toBe("alice@example.com");
        });

        it("AC16.5.3 stores token when provided", () => {
            setUser("user-456", "alice@example.com", "token-abc");
            expect(localStorage.getItem("finance_access_token")).toBe("token-abc");
        });

        it("AC16.5.3 does not set token when not provided", () => {
            setUser("user-456", "alice@example.com");
            expect(localStorage.getItem("finance_access_token")).toBeNull();
        });
    });

    describe("clearUser", () => {
        it("AC16.5.4 removes all auth keys from localStorage", () => {
            setUser("user-789", "bob@example.com", "my-token");
            clearUser();
            expect(localStorage.getItem("finance_user_id")).toBeNull();
            expect(localStorage.getItem("finance_user_email")).toBeNull();
            expect(localStorage.getItem("finance_access_token")).toBeNull();
        });
    });

    describe("isAuthenticated", () => {
        it("AC16.5.5 returns false when no token is stored", () => {
            expect(isAuthenticated()).toBe(false);
        });

        it("AC16.5.5 returns true when token exists in localStorage", () => {
            localStorage.setItem("finance_access_token", "valid-token");
            expect(isAuthenticated()).toBe(true);
        });
    });
});
