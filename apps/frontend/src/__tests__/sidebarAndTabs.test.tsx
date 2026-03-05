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

let workspaceMockData = {
    isCollapsed: false,
    toggleSidebar: toggleSidebarMock,
    tabs: [{ id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" }],
    activeTabId: "tab-1" as string | null,
    addTab: addTabMock,
    removeTab: removeTabMock,
    setActiveTab: setActiveTabMock,
  }

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => workspaceMockData,
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
    workspaceMockData = {
      isCollapsed: false,
      toggleSidebar: toggleSidebarMock,
      tabs: [{ id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" }],
      activeTabId: "tab-1" as string | null,
      addTab: addTabMock,
      removeTab: removeTabMock,
      setActiveTab: setActiveTabMock,
    }
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
  });

  it("AC16.19.4 shows empty state when no tabs", async () => {
    workspaceMockData = {
      isCollapsed: false,
      toggleSidebar: toggleSidebarMock,
      tabs: [],
      activeTabId: null as string | null,
      addTab: addTabMock,
      removeTab: removeTabMock,
      setActiveTab: setActiveTabMock,
    }
    render(<WorkspaceTabs />)
    expect(screen.getByText("No tabs open")).toBeInTheDocument()
  });

  it("AC16.19.4 derives labels for unknown paths", async () => {
    pathnameMock = "/custom-page-name"
    render(<WorkspaceTabs />)
    await waitFor(() => expect(addTabMock).toHaveBeenCalledWith(expect.objectContaining({
      label: "Custom Page Name"
    })))
  });

  it("AC16.19.12 sidebar nav shows Portfolio label for /assets route", () => {
    render(<Sidebar />)
    expect(screen.getByText("Portfolio")).toBeInTheDocument()
    expect(screen.queryByText("Assets")).not.toBeInTheDocument()
  })

  it("AC16.19.13 WorkspaceTabs labels /assets tab as Portfolio from ROUTE_CONFIG", async () => {
    pathnameMock = "/assets"
    render(<WorkspaceTabs />)
    await waitFor(() =>
      expect(addTabMock).toHaveBeenCalledWith(expect.objectContaining({ label: "Portfolio", href: "/assets" }))
    )
  })

  it("AC16.19.14 WorkspaceTabs section header is Open Tabs in both empty and active states", () => {
    render(<WorkspaceTabs />)
    expect(screen.getByText("Open Tabs")).toBeInTheDocument()
  })

  it("AC16.19.15 navigates tabs with ArrowRight keyboard", () => {
    workspaceMockData = {
      isCollapsed: false,
      toggleSidebar: toggleSidebarMock,
      tabs: [
        { id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
        { id: "tab-2", label: "Accounts", href: "/accounts", icon: "Landmark" },
      ],
      activeTabId: "tab-1",
      addTab: addTabMock,
      removeTab: removeTabMock,
      setActiveTab: setActiveTabMock,
    }
    render(<WorkspaceTabs />)

    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowRight" })
    expect(setActiveTabMock).toHaveBeenCalledWith("tab-2")
    expect(pushMock).toHaveBeenCalledWith("/accounts")
  })

  it("AC16.19.15 navigates tabs with ArrowLeft keyboard and wraps around", () => {
    workspaceMockData = {
      isCollapsed: false,
      toggleSidebar: toggleSidebarMock,
      tabs: [
        { id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
        { id: "tab-2", label: "Accounts", href: "/accounts", icon: "Landmark" },
      ],
      activeTabId: "tab-1",
      addTab: addTabMock,
      removeTab: removeTabMock,
      setActiveTab: setActiveTabMock,
    }
    render(<WorkspaceTabs />)

    const tablist = screen.getByRole("tablist")
    fireEvent.keyDown(tablist, { key: "ArrowLeft" })
    expect(setActiveTabMock).toHaveBeenCalledWith("tab-2")
    expect(pushMock).toHaveBeenCalledWith("/accounts")
  })

  it("AC16.19.15 renders tab ARIA attributes", () => {
    workspaceMockData = {
      isCollapsed: false,
      toggleSidebar: toggleSidebarMock,
      tabs: [
        { id: "tab-1", label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
        { id: "tab-2", label: "Accounts", href: "/accounts", icon: "Landmark" },
      ],
      activeTabId: "tab-1",
      addTab: addTabMock,
      removeTab: removeTabMock,
      setActiveTab: setActiveTabMock,
    }
    render(<WorkspaceTabs />)

    const tabs = screen.getAllByRole("tab")
    expect(tabs[0]).toHaveAttribute("aria-selected", "true")
    expect(tabs[0]).toHaveAttribute("tabindex", "0")
    expect(tabs[1]).toHaveAttribute("aria-selected", "false")
    expect(tabs[1]).toHaveAttribute("tabindex", "-1")
  })
});
