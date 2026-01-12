"use client";

import { useEffect, useState } from "react";
import { getTheme, toggleTheme, initTheme, type Theme } from "@/lib/theme";

export function ThemeToggle() {
    const [theme, setThemeState] = useState<Theme>("light");
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        initTheme();
        setThemeState(getTheme());
        setMounted(true);
    }, []);

    const handleToggle = () => {
        const newTheme = toggleTheme();
        setThemeState(newTheme);
    };

    // Avoid hydration mismatch
    if (!mounted) {
        return (
            <button className="p-1.5 rounded-md hover:bg-[var(--background-muted)] text-muted transition-colors w-8 h-8" />
        );
    }

    return (
        <button
            onClick={handleToggle}
            className="p-1.5 rounded-md hover:bg-[var(--background-muted)] text-muted transition-colors"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
            {theme === "dark" ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
            ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
            )}
        </button>
    );
}
