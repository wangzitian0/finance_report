import { beforeEach, expect, it, vi } from "vitest";
import { getTheme, initTheme, setTheme, toggleTheme } from "../lib/theme";
const stubMM = (dark: boolean) =>
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn((q: string) => ({
      matches: dark && q === "(prefers-color-scheme: dark)",
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
  vi.restoreAllMocks();
});
it("AC16.7.1 AC16.7.2 AC16.7.3 AC16.7.4 theme helpers", () => {
  for (const [s, d, e] of [
    ["dark", false, "dark"],
    ["light", true, "light"],
    [null, true, "dark"],
    [null, false, "light"],
  ] as const) {
    window.localStorage.clear();
    if (s) window.localStorage.setItem("theme", s);
    stubMM(d);
    expect(getTheme()).toBe(e);
  }
  setTheme("dark");
  expect([
    document.documentElement.classList.contains("dark"),
    window.localStorage.getItem("theme"),
  ]).toEqual([true, "dark"]);
  setTheme("light");
  expect([
    document.documentElement.classList.contains("dark"),
    window.localStorage.getItem("theme"),
  ]).toEqual([false, "light"]);
  expect([
    toggleTheme(),
    document.documentElement.classList.contains("dark"),
  ]).toEqual(["dark", true]);
  expect([
    toggleTheme(),
    document.documentElement.classList.contains("dark"),
  ]).toEqual(["light", false]);
  window.localStorage.setItem("theme", "dark");
  initTheme();
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});
// AC-meta.fe-utils.5 AC-meta.fe-utils.6 AC-meta.fe-utils.7 AC-meta.fe-utils.8
