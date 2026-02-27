import { describe, it, expect, beforeEach, vi } from "vitest";
import { getTheme, setTheme, toggleTheme, initTheme } from "../lib/theme";

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

describe("theme utilities", () => {
    beforeEach(() => {
        localStorageMock.clear();
        document.documentElement.className = "";
        vi.restoreAllMocks();
    });

    describe("getTheme", () => {
        it("AC16.7.1 returns stored dark theme from localStorage", () => {
            localStorage.setItem("theme", "dark");
            expect(getTheme()).toBe("dark");
        });

        it("AC16.7.1 returns stored light theme from localStorage", () => {
            localStorage.setItem("theme", "light");
            expect(getTheme()).toBe("light");
        });

        it("AC16.7.1 returns system preference dark when no stored value", () => {
            Object.defineProperty(window, "matchMedia", {
                writable: true,
                value: vi.fn().mockImplementation((query: string) => ({
                    matches: query === "(prefers-color-scheme: dark)",
                    media: query,
                    onchange: null,
                    addListener: vi.fn(),
                    removeListener: vi.fn(),
                    addEventListener: vi.fn(),
                    removeEventListener: vi.fn(),
                    dispatchEvent: vi.fn(),
                })),
            });
            expect(getTheme()).toBe("dark");
        });

        it("AC16.7.1 returns light when no stored value and system prefers light", () => {
            Object.defineProperty(window, "matchMedia", {
                writable: true,
                value: vi.fn().mockImplementation((query: string) => ({
                    matches: false,
                    media: query,
                    onchange: null,
                    addListener: vi.fn(),
                    removeListener: vi.fn(),
                    addEventListener: vi.fn(),
                    removeEventListener: vi.fn(),
                    dispatchEvent: vi.fn(),
                })),
            });
            expect(getTheme()).toBe("light");
        });
    });

    describe("setTheme", () => {
        it("AC16.7.2 adds dark class when setting dark theme", () => {
            setTheme("dark");
            expect(document.documentElement.classList.contains("dark")).toBe(true);
            expect(localStorage.getItem("theme")).toBe("dark");
        });

        it("AC16.7.2 removes dark class when setting light theme", () => {
            document.documentElement.classList.add("dark");
            setTheme("light");
            expect(document.documentElement.classList.contains("dark")).toBe(false);
            expect(localStorage.getItem("theme")).toBe("light");
        });
    });

    describe("toggleTheme", () => {
        it("AC16.7.3 toggles from light to dark", () => {
            localStorage.setItem("theme", "light");
            const result = toggleTheme();
            expect(result).toBe("dark");
            expect(document.documentElement.classList.contains("dark")).toBe(true);
        });

        it("AC16.7.3 toggles from dark to light", () => {
            localStorage.setItem("theme", "dark");
            const result = toggleTheme();
            expect(result).toBe("light");
            expect(document.documentElement.classList.contains("dark")).toBe(false);
        });
    });

    describe("initTheme", () => {
        it("AC16.7.4 initializes theme from stored value", () => {
            localStorage.setItem("theme", "dark");
            initTheme();
            expect(document.documentElement.classList.contains("dark")).toBe(true);
        });
    });
});
