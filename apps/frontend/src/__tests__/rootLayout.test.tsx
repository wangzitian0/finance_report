import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import RootLayout, { metadata, viewport } from "@/app/layout"
import { analyticsClientIdMissingInDeployedEnv } from "@/lib/analytics-env"

vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-inter" }),
}))

vi.mock("@/components/AuthGuard", () => ({
  AuthGuard: ({ children }: { children: ReactNode }) => <div data-testid="auth-guard">{children}</div>,
}))

vi.mock("@/components/Analytics", () => ({
  Analytics: () => <div data-testid="analytics" />,
}))

vi.mock("@/app/providers", () => ({
  Providers: ({ children }: { children: ReactNode }) => <div data-testid="providers">{children}</div>,
}))

describe("RootLayout", () => {
  // AC-meta.fe-app-shell.6
  it("AC16.17.5 composes Providers and AuthGuard around children", () => {
    render(
      <RootLayout>
        <div>Root Child</div>
      </RootLayout>,
    )

    expect(screen.getByTestId("providers")).toBeInTheDocument()
    expect(screen.getByTestId("auth-guard")).toBeInTheDocument()
    expect(screen.getByText("Root Child")).toBeInTheDocument()
  })

  it("Infra-014 C5: warns once per process when client id is missing in a deployed env", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    const prevUrl = process.env.NEXT_PUBLIC_APP_URL
    const prevId = process.env.OPENPANEL_CLIENT_ID
    process.env.NEXT_PUBLIC_APP_URL = "https://report.zitian.party"
    delete process.env.OPENPANEL_CLIENT_ID
    try {
      render(<RootLayout><div>a</div></RootLayout>)
      render(<RootLayout><div>b</div></RootLayout>)
      // force-dynamic runs per request, but the module-level guard logs only once.
      expect(errorSpy).toHaveBeenCalledTimes(1)
      expect(String(errorSpy.mock.calls[0]?.[0])).toContain("OPENPANEL_CLIENT_ID is empty")
    } finally {
      errorSpy.mockRestore()
      if (prevUrl === undefined) delete process.env.NEXT_PUBLIC_APP_URL
      else process.env.NEXT_PUBLIC_APP_URL = prevUrl
      if (prevId === undefined) delete process.env.OPENPANEL_CLIENT_ID
      else process.env.OPENPANEL_CLIENT_ID = prevId
    }
  })

  it("Infra-014 C5: flags a missing OpenPanel client id only in deployed non-preview envs", () => {
    // Deployed (staging/production https hosts) without a client id -> surfaced.
    expect(analyticsClientIdMissingInDeployedEnv(undefined, "https://report.zitian.party")).toBe(true)
    expect(analyticsClientIdMissingInDeployedEnv("", "https://report-staging.zitian.party")).toBe(true)
    // Preview and local are intentionally OpenPanel-less -> silent.
    expect(analyticsClientIdMissingInDeployedEnv(undefined, "https://report-pr-7.zitian.party")).toBe(false)
    expect(analyticsClientIdMissingInDeployedEnv(undefined, "http://localhost:3000")).toBe(false)
    expect(analyticsClientIdMissingInDeployedEnv(undefined, undefined)).toBe(false)
    // A configured client id is never flagged.
    expect(analyticsClientIdMissingInDeployedEnv("abc-123", "https://report.zitian.party")).toBe(false)
  })

  // AC-meta.fe-app-shell.21
  it("AC16.25.4 root layout metadata keeps viewport-only theme color", () => {
    expect(metadata).not.toHaveProperty("themeColor")
    expect(viewport.themeColor).toBe("#7c3aed")
    expect(metadata.appleWebApp).toEqual({
      capable: true,
      title: "Finance Report",
      statusBarStyle: "default",
    })
    expect(metadata.other).toEqual({
      "mobile-web-app-capable": "yes",
    })
  })
})
