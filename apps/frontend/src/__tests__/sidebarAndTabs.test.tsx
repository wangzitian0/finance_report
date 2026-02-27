import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Sidebar } from "@/components/Sidebar"
import { WorkspaceTabs } from "@/components/WorkspaceTabs"

const pushMock = vi.fn()
const toggleSidebarMock = vi.fn()
const addTabMock = vi.fn()
const removeTabMock = vi.fn()
const setActiveTabMock = vi.fn()
const clearUserMock = vi.fn()
const getUserEmailMock = vi.fn()
const isAuthenticatedMock = vi.fn()

let pathnameMock = "/dashboard"

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock,
  useRouter: () => ({ push: pushMock }),
}))

vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => <div>Theme Toggle</div>,
}))

vi.mock("@/lib/auth", () => ({
  clearUser: () => clearUserMock(),
  getUserEmail: () => getUserEmailMock(),
  isAuthenticated: () => isAuthenticatedMock(),
}))

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    isCollapsed: false,
    toggleSidebar: toggleSidebarMock,
    tabs: [{ id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" }],
    activeTabId: "tab-1",
    addTab: addTabMock,
    removeTab: removeTabMock,
    setActiveTab: setActiveTabMock,
  }),
}))

describe("Sidebar and WorkspaceTabs", () => {
  beforeEach(() => {
    pushMock.mockReset()
    toggleSidebarMock.mockReset()
    addTabMock.mockReset()
    removeTabMock.mockReset()
    setActiveTabMock.mockReset()
    clearUserMock.mockReset()
    getUserEmailMock.mockReset()
    isAuthenticatedMock.mockReset()
    pathnameMock = "/dashboard"
    getUserEmailMock.mockReturnValue("user@example.com")
    isAuthenticatedMock.mockReturnValue(true)
  })

  it("AC16.19.3 shows auth-aware sidebar actions and logout behavior", async () => {
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByText("Dashboard")).toBeInTheDocument())
    expect(screen.getByText("user@example.com")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Logout" }))
    expect(clearUserMock).toHaveBeenCalledTimes(1)
    expect(pushMock).toHaveBeenCalledWith("/login")
  })

  it("AC16.19.4 adds and manages workspace tabs from route changes", async () => {
    pathnameMock = "/reports/balance-sheet"
    render(<WorkspaceTabs />)

    await waitFor(() => expect(addTabMock).toHaveBeenCalled())
    fireEvent.click(screen.getByText("Dashboard"))
    expect(setActiveTabMock).toHaveBeenCalledWith("tab-1")

    fireEvent.click(screen.getByLabelText("Close Dashboard tab"))
    expect(removeTabMock).toHaveBeenCalledWith("tab-1")
  })
})
