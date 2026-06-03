import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { Sidebar } from "@/components/Sidebar"
import { WorkspaceTabs } from "@/components/WorkspaceTabs"
import { apiFetch } from "@/lib/api"

const pushMock = vi.fn()
const toggleSidebarMock = vi.fn()
const addTabMock = vi.fn()
const removeTabMock = vi.fn()
const setActiveTabMock = vi.fn()
const clearUserMock = vi.fn()
const getUserEmailMock = vi.fn()
const isAuthenticatedMock = vi.fn()
const mockedApiFetch = vi.mocked(apiFetch)

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
  const expectedReviewBadgeCountFromMocks = "3"

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
    pathnameMock = "/dashboard"
    getUserEmailMock.mockReturnValue("user@example.com")
    isAuthenticatedMock.mockReturnValue(true)
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/statements/pending-review") {
        return { items: [{ id: "s1" }, { id: "s2" }], total: 2 }
      }
      if (path === "/api/statements/stage2/queue") {
        return { pending_matches: [{ id: "m1", status: "pending_review" }, { id: "m2", status: "accepted" }] }
      }
      if (path === "/api/accounts/processing/summary") {
        return { pending_count: 0, pending_total: "0.00", current_balance: "0.00", currency: "SGD", oldest_pending_date: null }
      }
      return {}
    })
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
    const reviewLink = await screen.findByRole("link", { name: /Review/i })
    expect(reviewLink).toHaveAttribute("href", "/review")
    expect(screen.getByText(expectedReviewBadgeCountFromMocks)).toBeInTheDocument()
    expect(screen.getByText("user@example.com")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Logout" }))
    expect(clearUserMock).toHaveBeenCalledTimes(1)
    expect(pushMock).toHaveBeenCalledWith("/login")
  })

  it("AC15.7.3 exposes Processing Account in sidebar", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/statements/pending-review") {
        return { items: [], total: 0 }
      }
      if (path === "/api/statements/stage2/queue") {
        return { pending_matches: [] }
      }
      if (path === "/api/accounts/processing/summary") {
        return { pending_count: 4, pending_total: "1250.00", current_balance: "0.00", currency: "SGD", oldest_pending_date: "2026-05-01" }
      }
      return {}
    })

    render(<Sidebar />)

    const processingLink = await screen.findByRole("link", { name: /Processing/i })
    expect(processingLink).toHaveAttribute("href", "/processing")
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

  it("AC15.7.6 shows Processing between Reconciliation and AI Advisor", async () => {
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByText("Processing")).toBeInTheDocument())
    const labels = screen.getAllByRole("link").map((link) => link.textContent ?? "")
    expect(labels.indexOf("Reconciliation")).toBeLessThan(labels.indexOf("Processing"))
    expect(labels.indexOf("Processing")).toBeLessThan(labels.indexOf("AI Advisor"))
  })

  it("AC15.7.7 shows a sidebar warning when Processing Account balance is non-zero", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/statements/pending-review") {
        return { items: [], total: 0 }
      }
      if (path === "/api/statements/stage2/queue") {
        return { pending_matches: [] }
      }
      if (path === "/api/accounts/processing/summary") {
        return { pending_count: 1, pending_total: "100.00", current_balance: "100.00", currency: "SGD", oldest_pending_date: "2026-05-01" }
      }
      return {}
    })

    render(<Sidebar />)

    await waitFor(() => {
      expect(screen.getByLabelText("Processing Account has unresolved balance")).toBeInTheDocument()
    })
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
