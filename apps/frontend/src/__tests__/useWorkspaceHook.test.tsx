import { render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import * as X from "./helpers/shellTestFixtures";

function Harness() {
  const w = useWorkspace();
  return (
    <div>
      <div data-testid="tabs">{JSON.stringify(w.tabs)}</div>
      <div data-testid="act">{w.activeTabId ?? "none"}</div>
      <div data-testid="col">{String(w.isCollapsed)}</div>
      <button onClick={() => w.addTab({ label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" })}>AddD</button>
      <button onClick={() => w.addTab({ label: "Reports", href: "/reports", icon: "FileText" })}>AddR</button>
      <button onClick={() => w.removeTab(w.tabs[0]?.id ?? "")}>Rem1</button>
      <button onClick={() => w.removeTab(w.tabs[1]?.id ?? "")}>Rem2</button>
      <button onClick={() => w.setActiveTab(w.tabs[0]?.id ?? "")}>Act1</button>
      <button onClick={() => w.toggleSidebar()}>Tog</button>
    </div>
  );
}
const renderWs = () => R(<WorkspaceProvider><Harness /></WorkspaceProvider>);

describe("useWorkspace", () => {
  const store = new Map<string, string>(), uuid = vi.fn();
  beforeEach(() => X.stubWsStorage(store, uuid));

  it("throws outside provider; hydrates & manages tabs", async () => {
    const Bad = () => { useWorkspace(); return null; };
    E(() => R(<Bad />)).toThrow("useWorkspace must be used within a WorkspaceProvider");
    store.set("finance-workspace-tabs", X.WS_STORED);
    const hyd = renderWs(); await W(() => E(S.getByTestId("act")).toHaveTextContent("s2")); E(S.getByTestId("tabs")).toHaveTextContent("Stored Dashboard"); hyd.unmount();
    store.clear(); renderWs(); await X.runWsCrudFlow(store);
  });

  it("syncs storage, toggles sidebar, fallback ID, dev errors", () => X.runWsSyncAndErrors(renderWs, store));
});
// AC-meta.fe-app-shell.19-20
