import { describe, it, expect, vi } from "vitest";

describe("theme SSR coverage", () => {
    it("returns light and no-ops in setTheme when window is undefined", async () => {
        vi.resetModules();
        const g = globalThis as { window?: unknown };
        const originalWindow = g.window;
        delete g.window;
        const { getTheme, setTheme } = await import("@/lib/theme");
        expect(getTheme()).toBe("light");
        expect(() => setTheme("dark")).not.toThrow();
        g.window = originalWindow;
    });
});
