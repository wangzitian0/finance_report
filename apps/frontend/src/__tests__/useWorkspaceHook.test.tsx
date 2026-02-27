import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace"

function WorkspaceHarness() {
  const workspace = useWorkspace()

  return (
    <div>
      <div data-testid="tabs-json">{JSON.stringify(workspace.tabs)}</div>
      <div data-testid="active-id">{workspace.activeTabId ?? "none"}</div>
      <div data-testid="collapsed">{workspace.isCollapsed ? "true" : "false"}</div>

      <button onClick={() => workspace.addTab({ label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" })}>Add Dashboard</button>
      <button onClick={() => workspace.addTab({ label: "Reports", href: "/reports", icon: "FileText" })}>Add Reports</button>
      <button onClick={() => workspace.removeTab(workspace.tabs[0]?.id ?? "")}>Remove First</button>
      <button onClick={() => workspace.removeTab(workspace.tabs[1]?.id ?? "")}>Remove Second</button>
      <button onClick={() => workspace.setActiveTab(workspace.tabs[0]?.id ?? "")}>Activate First</button>
      <button onClick={() => workspace.toggleSidebar()}>Toggle Sidebar</button>
    </div>
  )
}

describe("useWorkspace and WorkspaceProvider", () => {
  const storage = new Map<string, string>()
  const randomUUIDMock = vi.fn()
  const randomMock = vi.spyOn(Math, "random")

  beforeEach(() => {
    storage.clear()
    randomUUIDMock.mockReset()
    randomUUIDMock.mockReturnValueOnce("tab-uuid-1").mockReturnValueOnce("tab-uuid-2").mockReturnValueOnce("tab-uuid-3")

    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })

    vi.stubGlobal("crypto", { randomUUID: randomUUIDMock })
    randomMock.mockReturnValue(0.123456789)
  })

  it("throws when useWorkspace is called outside provider", () => {
    const BadConsumer = () => {
      useWorkspace()
      return <div>bad</div>
    }

    expect(() => render(<BadConsumer />)).toThrow("useWorkspace must be used within a WorkspaceProvider")
  })

  it("AC16.21.9 hydrates tabs from localStorage and keeps active tab", async () => {
    storage.set(
      "finance-workspace-tabs",
      JSON.stringify({
        tabs: [
          { id: "stored-1", label: "Stored Dashboard", href: "/dashboard" },
          { id: "stored-2", label: "Stored Reports", href: "/reports" },
        ],
        activeTabId: "stored-2",
      }),
    )

    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    await waitFor(() => expect(screen.getByTestId("active-id").textContent).toBe("stored-2"))
    const tabsJson = screen.getByTestId("tabs-json").textContent ?? ""
    expect(tabsJson).toContain("Stored Dashboard")
    expect(tabsJson).toContain("Stored Reports")
  })

  it("AC16.21.9 persists tab additions and active state", async () => {
    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Add Dashboard" }))

    await waitFor(() => expect(screen.getByTestId("tabs-json").textContent).toContain("Dashboard"))
    expect(screen.getByTestId("active-id").textContent).toBe("tab-uuid-1")

    const persisted = storage.get("finance-workspace-tabs") ?? ""
    expect(persisted).toContain("Dashboard")
    expect(persisted).toContain("tab-uuid-1")
  })

  it("AC16.21.10 deduplicates tabs by href and keeps existing active id", async () => {
    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Add Dashboard" }))
    fireEvent.click(screen.getByRole("button", { name: "Add Reports" }))
    await waitFor(() => expect(screen.getByTestId("tabs-json").textContent).toContain("Reports"))

    const activeBeforeDedup = screen.getByTestId("active-id").textContent
    expect(activeBeforeDedup).toBe("tab-uuid-2")

    fireEvent.click(screen.getByRole("button", { name: "Add Dashboard" }))

    await waitFor(() => {
      const tabs = JSON.parse(screen.getByTestId("tabs-json").textContent ?? "[]") as Array<{ href: string }>
      const dashboardTabs = tabs.filter((t) => t.href === "/dashboard")
      expect(dashboardTabs).toHaveLength(1)
    })
    expect(screen.getByTestId("active-id").textContent).toBe("tab-uuid-1")
  })

  it("AC16.21.10 removes active tab and selects nearest remaining tab", async () => {
    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Add Dashboard" }))
    fireEvent.click(screen.getByRole("button", { name: "Add Reports" }))

    await waitFor(() => expect(screen.getByTestId("active-id").textContent).toBe("tab-uuid-2"))

    fireEvent.click(screen.getByRole("button", { name: "Remove Second" }))
    await waitFor(() => expect(screen.getByTestId("active-id").textContent).toBe("tab-uuid-1"))

    fireEvent.click(screen.getByRole("button", { name: "Remove First" }))
    await waitFor(() => expect(screen.getByTestId("tabs-json").textContent).toBe("[]"))
  })

  it("AC16.21.10 syncs tabs from storage events", async () => {
    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "finance-workspace-tabs",
          newValue: JSON.stringify({
            tabs: [{ id: "remote-1", label: "Remote", href: "/remote" }],
            activeTabId: "remote-1",
          }),
        }),
      )
    })

    await waitFor(() => expect(screen.getByTestId("tabs-json").textContent).toContain("Remote"))
    expect(screen.getByTestId("active-id").textContent).toBe("remote-1")
  })

  it("toggles sidebar collapsed state", async () => {
    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    expect(screen.getByTestId("collapsed").textContent).toBe("false")
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sidebar" }))
    await waitFor(() => expect(screen.getByTestId("collapsed").textContent).toBe("true"))
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sidebar" }))
    await waitFor(() => expect(screen.getByTestId("collapsed").textContent).toBe("false"))
  })

  it("falls back to Math.random id generation when randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", {})

    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Add Dashboard" }))

    await waitFor(() => {
      const tabs = JSON.parse(screen.getByTestId("tabs-json").textContent ?? "[]") as Array<{ id: string }>
      expect(tabs[0]?.id).toBe("4fzzzxj")
    })
  })

  it("ignores malformed storage payload without crashing", async () => {
    storage.set("finance-workspace-tabs", "not-json")

    render(
      <WorkspaceProvider>
        <WorkspaceHarness />
      </WorkspaceProvider>,
    )

    await waitFor(() => expect(screen.getByTestId("tabs-json").textContent).toBe("[]"))
  })
})
