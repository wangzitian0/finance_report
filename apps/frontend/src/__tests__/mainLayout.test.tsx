import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import MainLayout from "@/app/(main)/layout"

vi.mock("@/components/AppShell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div data-testid="app-shell">{children}</div>,
}))

describe("MainLayout", () => {
  it("AC16.16.2 renders children through AppShell", () => {
    render(
      <MainLayout>
        <div>Child Content</div>
      </MainLayout>,
    )

    expect(screen.getByTestId("app-shell")).toBeInTheDocument()
    expect(screen.getByText("Child Content")).toBeInTheDocument()
  })
})
