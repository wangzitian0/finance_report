import "@testing-library/jest-dom/vitest"
import { render, screen } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

import ConfidenceBadge from "@/components/ui/ConfidenceBadge"
import tailwindConfig from "../../tailwind.config"

const extend = tailwindConfig.theme?.extend as Record<string, unknown>

describe("frontend design tokens", () => {
  it("AC16.29.1 AC16.29.4 maps Tailwind theme values to CSS-variable design tokens", () => {
    expect(extend.colors).toMatchObject({
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
        warning: "var(--warning)",
        error: "var(--error)",
        info: "var(--info)",
      },
      chart: {
        1: "var(--chart-1)",
        5: "var(--chart-5)",
        "trend-start": "var(--chart-trend-start)",
      },
    })

    expect(extend.borderRadius).toMatchObject({
      control: "var(--radius-md)",
      panel: "var(--radius-lg)",
    })
    expect(extend.fontSize).toMatchObject({
      caption: ["var(--font-size-caption)", { lineHeight: "var(--line-height-caption)" }],
      body: ["var(--font-size-body)", { lineHeight: "var(--line-height-body)" }],
      title: ["var(--font-size-title)", { lineHeight: "var(--line-height-title)" }],
    })
    expect(extend.spacing).toMatchObject({
      page: "var(--space-page)",
      panel: "var(--space-panel)",
      control: "var(--space-control)",
    })
    expect(extend.boxShadow).toMatchObject({
      card: "var(--shadow-card)",
      floating: "var(--shadow-floating)",
    })
    expect(extend.zIndex).toMatchObject({
      overlay: "var(--z-overlay)",
      modal: "var(--z-modal)",
    })
    expect(extend.transitionDuration).toMatchObject({
      fast: "var(--motion-duration-fast)",
      standard: "var(--motion-duration-standard)",
    })
    expect(extend.transitionTimingFunction).toMatchObject({
      standard: "var(--motion-ease-standard)",
    })
  })

  it("AC16.29.2 AC16.29.4 documents token usage and page-local visual decisions in SSOT", () => {
    const ssot = readFileSync(
      resolve(process.cwd(), "../../docs/ssot/frontend-patterns.md"),
      "utf8",
    )

    expect(ssot).toContain("## 4. Design Tokens")
    expect(ssot).toContain("### Token Families")
    expect(ssot).toContain("### Page-Local Visual Decisions")
    expect(ssot).toContain("Login uses the accent gradient")
    expect(ssot).toContain("Dashboard cards and chart panels")
  })

  it("AC16.30.2 AC16.30.6 keeps SSOT and CSS recipes on semantic border and status tokens", () => {
    const ssot = readFileSync(
      resolve(process.cwd(), "../../docs/ssot/frontend-patterns.md"),
      "utf8",
    )
    const globals = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8")

    expect(ssot).toContain("**Border colors**")
    expect(ssot).toContain("Use `border-border`")
    expect(ssot).toContain("```text")
    expect(globals).not.toContain("border-[var(--border)]")
    expect(globals).toContain("border-border")
    expect(globals).toContain("bg-status-error-muted text-status-error")
    expect(globals).toContain("bg-status-success-muted text-status-success")
    expect(globals).toContain("bg-status-warning-muted text-status-warning")
    expect(globals).toContain("bg-status-info-muted text-status-info")
    expect(globals).not.toMatch(/alert bg-\[var\(--(error|success|warning|info)-muted\)\] text-\[var\(--(error|success|warning|info)\)\]/)
  })

  it("AC22.12.1 AC22.12.3 AC22.13.3 defines the global accessibility baseline in SSOT and CSS", () => {
    const ssot = readFileSync(
      resolve(process.cwd(), "../../docs/ssot/frontend-patterns.md"),
      "utf8",
    )
    const globals = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8")

    expect(ssot).toContain("### Global Accessibility Baseline")
    expect(ssot).toContain("`prefers-reduced-motion: reduce`")
    expect(ssot).toContain("`:focus-visible`")

    expect(globals).toContain("@media (prefers-reduced-motion: reduce)")
    expect(globals).toContain("animation-duration: 0.01ms !important")
    expect(globals).toContain("transition-duration: 0.01ms !important")
    expect(globals).toContain("scroll-behavior: auto !important")
    expect(globals).toContain(":focus-visible")
    expect(globals).toContain("[tabindex]:focus-visible")
    expect(globals).toContain('[tabindex="-1"]:focus')
    expect(globals).not.toContain('[tabindex]:not([tabindex="-1"])')
    expect(globals).toContain(".btn-primary:focus-visible")
    expect(globals).toContain("outline: 2px solid var(--accent)")
    expect(globals).toContain("box-shadow: var(--shadow-focus)")
  })

  it("AC22.20.4 defines the mobile standalone safe-area baseline in SSOT and CSS", () => {
    const ssot = readFileSync(
      resolve(process.cwd(), "../../docs/ssot/frontend-patterns.md"),
      "utf8",
    )
    const globals = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8")

    expect(ssot).toContain("### Mobile Install Baseline")
    expect(ssot).toContain("Add to Home Screen")
    expect(ssot).toContain("business pages must not listen for `beforeinstallprompt`")

    expect(globals).toContain(".pwa-safe-area-shell")
    expect(globals).toContain("min-height: 100dvh")
    expect(globals).toContain("env(safe-area-inset-top)")
    expect(globals).toContain("env(safe-area-inset-bottom)")
  })

  it("AC16.29.3 AC16.29.4 renders ConfidenceBadge variants through semantic token classes", () => {
    const tiers = ["TRUSTED", "HIGH", "MEDIUM", "LOW"] as const

    render(
      <div>
        {tiers.map((tier) => (
          <ConfidenceBadge key={tier} tier={tier} />
        ))}
      </div>,
    )

    expect(screen.getByText("TRUSTED")).toHaveClass("badge-success")
    expect(screen.getByText("HIGH")).toHaveClass("badge-info")
    expect(screen.getByText("MEDIUM")).toHaveClass("badge-warning")
    expect(screen.getByText("LOW")).toHaveClass("badge-muted")

    for (const tier of tiers) {
      const className = screen.getByText(tier).className
      expect(className).not.toMatch(/\bbg-(green|blue|amber|gray)-/)
      expect(className).not.toMatch(/\btext-(green|blue|amber|gray)-/)
    }
  })
})
