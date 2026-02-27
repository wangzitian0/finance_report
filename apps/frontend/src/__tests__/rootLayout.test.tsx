import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import RootLayout from "@/app/layout"

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
})
