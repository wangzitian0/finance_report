import type { Config } from "tailwindcss";

const config: Config = {
    content: [
        "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                surface: {
                    DEFAULT: "var(--background)",
                    card: "var(--background-card)",
                    muted: "var(--background-muted)",
                    overlay: "var(--overlay)",
                },
                content: {
                    DEFAULT: "var(--foreground)",
                    muted: "var(--foreground-muted)",
                    inverse: "var(--foreground-inverse)",
                },
                border: {
                    DEFAULT: "var(--border)",
                    hover: "var(--border-hover)",
                },
                accent: {
                    DEFAULT: "var(--accent)",
                    hover: "var(--accent-hover)",
                    muted: "var(--accent-muted)",
                },
                status: {
                    success: "var(--success)",
                    "success-muted": "var(--success-muted)",
                    warning: "var(--warning)",
                    "warning-muted": "var(--warning-muted)",
                    error: "var(--error)",
                    "error-muted": "var(--error-muted)",
                    info: "var(--info)",
                    "info-muted": "var(--info-muted)",
                },
                chart: {
                    1: "var(--chart-1)",
                    2: "var(--chart-2)",
                    3: "var(--chart-3)",
                    4: "var(--chart-4)",
                    5: "var(--chart-5)",
                    "trend-start": "var(--chart-trend-start)",
                    "trend-end": "var(--chart-trend-end)",
                },
            },
            fontFamily: {
                sans: ["var(--font-inter)"],
            },
            fontSize: {
                caption: ["var(--font-size-caption)", { lineHeight: "var(--line-height-caption)" }],
                body: ["var(--font-size-body)", { lineHeight: "var(--line-height-body)" }],
                title: ["var(--font-size-title)", { lineHeight: "var(--line-height-title)" }],
            },
            spacing: {
                page: "var(--space-page)",
                panel: "var(--space-panel)",
                control: "var(--space-control)",
            },
            borderRadius: {
                control: "var(--radius-md)",
                panel: "var(--radius-lg)",
                pill: "var(--radius-full)",
            },
            boxShadow: {
                card: "var(--shadow-card)",
                floating: "var(--shadow-floating)",
                focus: "var(--shadow-focus)",
            },
            zIndex: {
                drawer: "var(--z-drawer)",
                overlay: "var(--z-overlay)",
                modal: "var(--z-modal)",
                toast: "var(--z-toast)",
            },
            transitionDuration: {
                fast: "var(--motion-duration-fast)",
                standard: "var(--motion-duration-standard)",
                slow: "var(--motion-duration-slow)",
            },
            transitionTimingFunction: {
                standard: "var(--motion-ease-standard)",
                emphasized: "var(--motion-ease-emphasized)",
            },
        },
    },
    plugins: [],
};
export default config;
