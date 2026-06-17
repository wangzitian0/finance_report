import { render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AppShell } from "@/components/AppShell"
import { AuthGuard } from "@/components/AuthGuard"

const pushMock = vi.fn()
const isAuthenticatedMock = vi.fn()
let pathnameMock = "/dashboard"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => pathnameMock,
}))

vi.mock("@/lib/auth", () => ({
  isAuthenticated: () => isAuthenticatedMock(),
}))

// Session bootstrap (EPIC-022 AC22.15.3) has its own dedicated test; the shell
// layout tests stub it so they stay focused on layout/auth-guard behavior.
vi.mock("@/hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))

// The first-run LLM modal (EPIC-023 PR4) is mounted app-wide; it has its own
// dedicated test, so stub it here to keep the shell tests focused on layout.
vi.mock("@/components/llm/FirstRunModal", () => ({
  FirstRunModal: () => null,
}))

vi.mock("@/hooks/useWorkspace", () => ({
  WorkspaceProvider: ({ children }: { children: ReactNode }) => <div data-testid="workspace-provider">{children}</div>,
  useWorkspace: () => ({ isCollapsed: true }),
}))

vi.mock("@/components/Sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar">Sidebar</div>,
}))

vi.mock("@/components/WorkspaceTabs", () => ({
  WorkspaceTabs: () => <div data-testid="workspace-tabs">Tabs</div>,
}))

vi.mock("@/components/ui/Toast", () => ({
  ToastProvider: ({ children }: { children: ReactNode }) => <div data-testid="toast-provider">{children}</div>,
}))

describe("AppShell and AuthGuard", () => {
  beforeEach(() => {
    pushMock.mockReset()
    isAuthenticatedMock.mockReset()
    pathnameMock = "/dashboard"
  })

  it("AC16.19.1 renders providers and collapse-aware shell layout", () => {
    const { container } = render(
      <AppShell>
        <div>Shell Child</div>
      </AppShell>,
    )

    expect(screen.getByTestId("workspace-provider")).toBeInTheDocument()
    expect(screen.getByTestId("toast-provider")).toBeInTheDocument()
    expect(screen.getByTestId("sidebar")).toBeInTheDocument()
    expect(screen.getByTestId("workspace-tabs")).toBeInTheDocument()
    expect(screen.getByText("Shell Child")).toBeInTheDocument()
    expect(container.querySelector('[class*="md:ml-16"]')).not.toBeNull()
    expect(screen.getByTestId("workspace-tabs").parentElement?.className).toContain("hidden md:block")
  })

  it("AC22.12.2 exposes a skip-to-content link targeting the main landmark", () => {
    const { container } = render(
      <AppShell>
        <div>Shell Child</div>
      </AppShell>,
    )

    const skipLink = screen.getByRole("link", { name: "Skip to main content" })
    expect(skipLink).toHaveAttribute("href", "#main-content")
    expect(skipLink).toHaveClass("sr-only")
    expect(skipLink.className).toContain("focus:not-sr-only")

    const main = container.querySelector("main#main-content")
    expect(main).not.toBeNull()
    expect(main).toHaveAttribute("tabIndex", "-1")
  })

  it("AC16.19.2 redirects unauthenticated protected routes", async () => {
    isAuthenticatedMock.mockReturnValue(false)

    const { container } = render(
      <AuthGuard>
        <div>Protected Content</div>
      </AuthGuard>,
    )

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/login"))
    expect(container.textContent).toBe("")
  })

  it("AC16.19.2 allows public routes and handles auth storage logout", async () => {
    pathnameMock = "/login"
    isAuthenticatedMock.mockReturnValue(false)

    render(
      <AuthGuard>
        <div>Public Content</div>
      </AuthGuard>,
    )

    await waitFor(() => expect(screen.getByText("Public Content")).toBeInTheDocument())
  })

  it("AC16.19.2 handles storage logout for protected routes", async () => {
    pathnameMock = "/dashboard"
    isAuthenticatedMock.mockReturnValue(true)

    render(
      <AuthGuard>
        <div>Protected Content</div>
      </AuthGuard>,
    )

    await waitFor(() => expect(screen.getByText("Protected Content")).toBeInTheDocument())

    window.dispatchEvent(new StorageEvent("storage", { key: "finance_user_id", newValue: null }))
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/login"))
  })

  it("AC16.19.2 shows loading skeleton for unauthenticated protected routes", () => {
    isAuthenticatedMock.mockReturnValue(false)
    const { container } = render(
      <AuthGuard><div>Protected Content</div></AuthGuard>,
    )
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument()
    expect(container.querySelector(".animate-pulse")).not.toBeNull()
  })

  it("AC16.19.2 handles storage login event on login page", async () => {
    pathnameMock = "/login"
    isAuthenticatedMock.mockReturnValue(false)
    render(<AuthGuard><div>Login Content</div></AuthGuard>)
    await waitFor(() => expect(screen.getByText("Login Content")).toBeInTheDocument())
    window.dispatchEvent(new StorageEvent("storage", { key: "finance_user_id", newValue: "user-1" }))
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"))
  })

  it("AC16.19.2 ignores unrelated storage events", async () => {
    pathnameMock = "/dashboard"
    isAuthenticatedMock.mockReturnValue(true)
    render(<AuthGuard><div>Content</div></AuthGuard>)
    await waitFor(() => expect(screen.getByText("Content")).toBeInTheDocument())
    window.dispatchEvent(new StorageEvent("storage", { key: "other_key", newValue: null }))
    expect(screen.getByText("Content")).toBeInTheDocument()
    expect(pushMock).not.toHaveBeenCalled()
  })

})
