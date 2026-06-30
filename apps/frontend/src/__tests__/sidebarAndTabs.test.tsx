import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Sidebar } from "@/components/Sidebar"
import { WorkspaceTabs } from "@/components/WorkspaceTabs"
import { apiFetch, fetchWorkflowStatus } from "@/lib/api"
import type { WorkflowStatusResponse } from "@/lib/types"

const pushMock = vi.fn()
const toggleSidebarMock = vi.fn()
const addTabMock = vi.fn()
const removeTabMock = vi.fn()
const setActiveTabMock = vi.fn()
const clearUserMock = vi.fn()
const getUserEmailMock = vi.fn()
const isAuthenticatedMock = vi.fn()
const mockedApiFetch = vi.mocked(apiFetch)
const mockedFetchWorkflowStatus = vi.mocked(fetchWorkflowStatus)

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

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  fetchWorkflowStatus: vi.fn(),
}))

const defaultWorkflowStatus: WorkflowStatusResponse = {
  primary_state: "needs_action",
  next_action: {
    type: "review_required",
    count: 2,
    href: "/review",
    label: "Review required",
    summary: "Confirm the source or review item so trusted report preparation can continue.",
  },
  report_readiness: { state: "blocked", blocking_count: 1, href: "/reports/package" },
  event_counts: { unread: 4, action_required: 2, blocked: 1 },
}

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
    mockedApiFetch.mockReset()
    mockedFetchWorkflowStatus.mockReset()
    pathnameMock = "/dashboard"
    getUserEmailMock.mockReturnValue("user@example.com")
    isAuthenticatedMock.mockReturnValue(true)
    mockedApiFetch.mockResolvedValue({})
    mockedFetchWorkflowStatus.mockResolvedValue(defaultWorkflowStatus)
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

  it("AC16.19.3 AC22.21.2 shows auth-aware sidebar actions mirroring the bottom tabs", async () => {
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByRole("link", { name: /^Home$/i })).toBeInTheDocument())
    expect(screen.getByRole("link", { name: /^Chat$/i })).toHaveAttribute("href", "/chat")
    expect(screen.getByRole("link", { name: /^Audit$/i })).toHaveAttribute("href", "/audit")
    expect(screen.getByRole("link", { name: /^More$/i })).toHaveAttribute("href", "/more")
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument()
    expect(screen.getByText("user@example.com")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Logout" }))
    expect(clearUserMock).toHaveBeenCalledTimes(1)
    expect(pushMock).toHaveBeenCalledWith("/login")
  })

  it("AC22.1.3 links the sidebar brand to Home", async () => {
    render(<Sidebar />)
    const brand = await screen.findByRole("link", { name: /Finance Report home/i })
    expect(brand).toHaveAttribute("href", "/")
  })

  it("AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)", async () => {
    render(<Sidebar />)

    await screen.findByRole("link", { name: /^Home$/i })
    expect(screen.queryByRole("button", { name: /Advanced/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /Journal/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /^Reconciliation$/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /^Accounts$/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /^Upload$/i })).toBeNull()
    expect(screen.queryByRole("link", { name: /AI Settings/i })).toBeNull()
  })

  it("AC22.21.2 shows only Home and a Login link when unauthenticated", async () => {
    isAuthenticatedMock.mockReturnValue(false)
    getUserEmailMock.mockReturnValue(null)
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByRole("link", { name: /^Home$/i })).toBeInTheDocument())
    expect(screen.getByRole("link", { name: "Login" })).toHaveAttribute("href", "/login")
    expect(screen.queryByRole("link", { name: /^Chat$/i })).toBeNull()
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Logout" })).toBeNull()
  })

  it("AC22.21.2 renders a collapsed icon-only rail without text labels", async () => {
    workspaceMockData = { ...workspaceMockData, isCollapsed: true }
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByLabelText("Expand sidebar")).toBeInTheDocument())
    // Collapsed: the Add action is still reachable by its aria-label.
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument()
    // The user email row is hidden when collapsed.
    expect(screen.queryByText("user@example.com")).toBeNull()
  })

  it("AC22.21.2 toggles collapse and opens the Add sheet", async () => {
    pathnameMock = "/audit"
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByRole("link", { name: /^Audit$/i })).toBeInTheDocument())
    // The active route is marked.
    expect(screen.getByRole("link", { name: /^Audit$/i })).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    expect(toggleSidebarMock).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    expect(screen.getByRole("dialog", { name: "Add" })).toBeInTheDocument()
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

  it("AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowRight keyboard", () => {
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

    const navigation = screen.getByRole("navigation", { name: "Open workspace tabs" })
    fireEvent.keyDown(navigation, { key: "ArrowRight" })
    expect(setActiveTabMock).toHaveBeenCalledWith("tab-2")
    expect(pushMock).toHaveBeenCalledWith("/accounts")
  })

  it("AC16.19.15 AC16.30.3 AC16.30.4 navigates workspace pages with ArrowLeft keyboard and wraps around", () => {
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

    const navigation = screen.getByRole("navigation", { name: "Open workspace tabs" })
    fireEvent.keyDown(navigation, { key: "ArrowLeft" })
    expect(setActiveTabMock).toHaveBeenCalledWith("tab-2")
    expect(pushMock).toHaveBeenCalledWith("/accounts")
  })

  it("AC16.30.3 AC16.30.4 renders route navigation semantics instead of ARIA tabs", () => {
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

    const navigation = screen.getByRole("navigation", { name: "Open workspace tabs" })
    expect(within(navigation).getByRole("list")).toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryAllByRole("tab")).toHaveLength(0)

    const dashboard = within(navigation).getByRole("link", { name: /Dashboard/ })
    const accounts = within(navigation).getByRole("link", { name: /Accounts/ })
    expect(dashboard).toHaveAttribute("aria-current", "page")
    expect(accounts).not.toHaveAttribute("aria-current")
  })
});
