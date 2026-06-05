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

  it("AC16.19.3 shows auth-aware sidebar actions and logout behavior", async () => {
    render(<Sidebar />)

    await waitFor(() => expect(screen.getByRole("link", { name: /Upload Pipeline/i })).toBeInTheDocument())
    expect(screen.getByRole("link", { name: /^AI$/i })).toHaveAttribute("href", "/chat")
    expect(screen.getByRole("button", { name: /Advanced/i })).toBeInTheDocument()
    expect(screen.getByText("user@example.com")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Logout" }))
    expect(clearUserMock).toHaveBeenCalledTimes(1)
    expect(pushMock).toHaveBeenCalledWith("/login")
  })

  it("AC19.6.3 exposes advanced accounting surfaces behind the Advanced group", async () => {
    render(<Sidebar />)

    fireEvent.click(await screen.findByRole("button", { name: /Advanced/i }))
    expect(screen.getByRole("link", { name: /Events/i })).toHaveAttribute("href", "/events")
    expect(screen.getByRole("link", { name: /Portfolio/i })).toHaveAttribute("href", "/portfolio")
    expect(screen.getByRole("link", { name: /Statements/i })).toHaveAttribute("href", "/statements")
    expect(screen.getByRole("link", { name: /Review/i })).toHaveAttribute("href", "/review")
    expect(screen.getByRole("link", { name: /Accounts/i })).toHaveAttribute("href", "/accounts")
    expect(screen.getByRole("link", { name: /Journal/i })).toHaveAttribute("href", "/journal")
    expect(screen.getByRole("link", { name: /Reconciliation/i })).toHaveAttribute("href", "/reconciliation")
    const processingLink = screen.getByRole("link", { name: /Processing/i })
    expect(processingLink).toHaveAttribute("href", "/processing")
    expect(screen.getByRole("link", { name: /AI Settings/i })).toHaveAttribute("href", "/settings/ai")
  })

  it("AC19.6.3 opens Advanced automatically for active advanced routes", async () => {
    pathnameMock = "/review/run/run-1"
    render(<Sidebar />)

    const advancedButton = await screen.findByRole("button", { name: /Advanced/i })
    expect(advancedButton).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("link", { name: /Review/i })).toHaveAttribute("href", "/review")
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

  it("AC16.19.12 sidebar nav shows Portfolio label for /assets route", async () => {
    render(<Sidebar />)
    fireEvent.click(await screen.findByRole("button", { name: /Advanced/i }))
    expect(await screen.findByText("Portfolio")).toBeInTheDocument()
    expect(screen.queryByText("Assets")).not.toBeInTheDocument()
  })

  it("AC15.7.6 AC19.6.3 shows Processing between Reconciliation and AI Settings in Advanced", async () => {
    render(<Sidebar />)

    fireEvent.click(await screen.findByRole("button", { name: /Advanced/i }))
    await waitFor(() => expect(screen.getByText("Processing")).toBeInTheDocument())
    const labels = screen.getAllByRole("link").map((link) => link.textContent ?? "")
    expect(labels.indexOf("Reconciliation")).toBeLessThan(labels.indexOf("Processing"))
    expect(labels.indexOf("Processing")).toBeLessThan(labels.indexOf("AI Settings"))
  })

  it("AC15.7.7 AC19.6.5 derives sidebar attention badges from workflow status instead of local processing or review polling", async () => {
    render(<Sidebar />)

    await waitFor(() => {
      expect(mockedFetchWorkflowStatus).toHaveBeenCalledTimes(1)
      expect(screen.getByRole("button", { name: /Advanced 3/i })).toBeInTheDocument()
    })
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/api/statements/pending-review")
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/api/statements/stage2/queue")
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/api/accounts/processing/summary")
  })

  it("AC19.6.5 clears sidebar workflow badges when workflow status is unavailable", async () => {
    mockedFetchWorkflowStatus.mockRejectedValue(new Error("workflow unavailable"))

    render(<Sidebar />)

    await waitFor(() => {
      expect(mockedFetchWorkflowStatus).toHaveBeenCalledTimes(1)
    })
    expect(screen.getByRole("button", { name: /^Advanced$/i })).toBeInTheDocument()
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
