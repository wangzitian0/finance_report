import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import RootLayout, { metadata, viewport } from "@/app/layout"

vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-inter" }),
}))

vi.mock("@/components/AuthGuard", () => ({
  AuthGuard: ({ children }: { children: ReactNode }) => <div data-testid="auth-guard">{children}</div>,
}))

vi.mock("@/app/providers", () => ({
  Providers: ({ children }: { children: ReactNode }) => <div data-testid="providers">{children}</div>,
}))

describe("RootLayout", () => {
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
