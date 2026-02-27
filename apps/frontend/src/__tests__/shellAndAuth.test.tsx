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
    expect(container.querySelector(".ml-16")).not.toBeNull()
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

    window.dispatchEvent(new StorageEvent("storage", { key: "finance_access_token", newValue: null }))
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/login"))
  })
})
