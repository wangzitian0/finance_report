import { fireEvent as F, render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { Sidebar, WorkspaceTabs } from "@/components/AppNav";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const push = vi.fn(), refresh = vi.fn(), toggleSidebar = vi.fn(), addTab = vi.fn(), removeTab = vi.fn(), setActiveTab = vi.fn();
const clearUser = vi.fn(), getUserEmail = vi.fn(), isAuthenticated = vi.fn();
const api = vi.mocked(apiOperation);
let path = "/dashboard", ws = { isCollapsed: false, toggleSidebar, tabs: [X.WORKSPACE_TAB_1], activeTabId: "tab-1" as string | null, addTab, removeTab, setActiveTab };

vi.mock("next/navigation", () => ({ usePathname: () => path, useRouter: () => ({ push, refresh }) }));
vi.mock("@/components/statements/StatementUploader", async () => (await import("./helpers/shellTestFixtures")).uploaderMock("Done"));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => <div>Theme</div> }));
vi.mock("@/lib/auth", () => ({ clearUser: () => clearUser(), getUserEmail: () => getUserEmail(), isAuthenticated: () => isAuthenticated() }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/hooks/useWorkspace", () => ({ useWorkspace: () => ws }));

describe("Sidebar & WorkspaceTabs", () => {
  beforeEach(() => {
    vi.clearAllMocks(); path = "/dashboard"; getUserEmail.mockReturnValue("user@example.com"); isAuthenticated.mockReturnValue(true); api.mockResolvedValue({} as never);
    ws = { isCollapsed: false, toggleSidebar, tabs: [X.WORKSPACE_TAB_1], activeTabId: "tab-1", addTab, removeTab, setActiveTab };
  });

  it("sidebar links & logout", async () => {
    let done!: () => void;
    api.mockReturnValueOnce(new Promise<void>((r) => { done = r; }) as never).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(undefined as never);
    const { container, unmount } = R(<Sidebar />); await X.runSidebarLogoutSuccess(api, clearUser, push, done, container); unmount();
    R(<Sidebar />); F.click(await S.findByRole("button", { name: "Logout" }));
    await X.findAlert("Could not log out. Please try again."); E(clearUser).toHaveBeenCalledTimes(1);
    X.clkBtn("Logout"); await W(() => E(push).toHaveBeenCalledTimes(2));
  });

  it("unauth, collapsed, Add-sheet", () =>
    X.runSidebarStates(() => R(<Sidebar />), (ok, e) => { isAuthenticated.mockReturnValue(ok); getUserEmail.mockReturnValue(e); }, (p) => { path = "/audit"; ws = { ...ws, ...p }; }, toggleSidebar, refresh));

  it.each(X.WORKSPACE_LABEL_CASES)("label %s", async (p, l) => { path = p; R(<WorkspaceTabs />); await W(() => E(addTab).toHaveBeenCalledWith(E.objectContaining({ label: l, href: p }))); });

  it("tabs, empty, keyboard", () =>
    X.runSidebarTabsChecks(() => R(<WorkspaceTabs />), (p) => { path = p; }, (p) => { ws = { ...ws, ...p }; }, addTab, setActiveTab, removeTab, push));
});
