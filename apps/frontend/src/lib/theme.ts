"use client";

const THEME_KEY = "theme";

export type Theme = "light" | "dark";

export function getTheme(): Theme {
    if (typeof window === "undefined") {
        // SSR: Return light as default. ThemeToggle component handles hydration
        // by waiting for mount before rendering the actual theme icon.
        return "light";
    }
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || stored === "light") {
        return stored;
    }
    // Check system preference
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        return "dark";
    }
    return "light";
}

export function setTheme(theme: Theme): void {
    if (typeof window === "undefined") {
        return;
    }
    localStorage.setItem(THEME_KEY, theme);
    if (theme === "dark") {
        document.documentElement.classList.add("dark");
    } else {
        document.documentElement.classList.remove("dark");
    }
}

export function toggleTheme(): Theme {
    const current = getTheme();
    const next = current === "dark" ? "light" : "dark";
    setTheme(next);
    return next;
}

export function initTheme(): void {
    const theme = getTheme();
    setTheme(theme);
}
