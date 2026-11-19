import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/RootClients";
const pushMock = vi.fn(), isAuth = vi.fn(), S = screen, E = expect;
let pathname = "/dashboard";
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }), usePathname: () => pathname }));
vi.mock("@/lib/auth", () => ({ isAuthenticated: () => isAuth() }));
vi.mock("@/hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }));
vi.mock("@/components/llm/FirstRunModal", () => ({ FirstRunModal: () => null }));
vi.mock("@/hooks/useWorkspace", () => ({ WorkspaceProvider: ({ children }: { children: ReactNode }) => <div data-testid="wp">{children}</div>, useWorkspace: () => ({ isCollapsed: true }) }));
vi.mock("@/components/AppNav", () => ({ Sidebar: () => <div data-testid="sb" />, WorkspaceTabs: () => <div data-testid="wt" /> }));
vi.mock("@/components/ui/Toast", () => ({ ToastProvider: ({ children }: { children: ReactNode }) => <div data-testid="tp">{children}</div> }));
beforeEach(() => { pushMock.mockReset(); isAuth.mockReset(); pathname = "/dashboard"; });
it("AC16.19.1 AC22.12.2 AC16.19.2 shell + auth", async () => {
const s = render(<AppShell><div>Child</div></AppShell>);
for (const id of ["wp", "tp", "sb", "wt"]) E(S.getByTestId(id)).toBeInTheDocument();
E(S.getByText("Child")).toBeInTheDocument();
E(s.container.querySelector('[class*="md:ml-16"]')).not.toBeNull();
E(S.getByTestId("wt").parentElement?.className).toContain("hidden md:block");
const skip = S.getByRole("link", { name: "Skip to main content" });
E(skip).toHaveAttribute("href", "#main-content");
E(skip).toHaveClass("sr-only");
E(skip.className).toContain("focus:not-sr-only");
E(s.container.querySelector("main#main-content")).toHaveAttribute("tabIndex", "-1");
s.unmount();
isAuth.mockReturnValue(false);
const g = render(<AuthGuard><div>Prot</div></AuthGuard>);
E(S.queryByText("Prot")).toBeNull();
E(g.container.querySelector(".animate-pulse")).not.toBeNull();
await waitFor(() => E(pushMock).toHaveBeenCalledWith("/login"));
E(g.container.textContent).toBe("");
});
it.each([["/dashboard", true, "other_key", null, null], ["/dashboard", true, "finance_user_id", null, "/login"], ["/login", false, "finance_user_id", "user-1", "/"]] as const)(
"AC16.19.2 %s %s",
async (p, a, k, v, exp) => {
pathname = p; isAuth.mockReturnValue(a);
render(<AuthGuard><div>Ok</div></AuthGuard>);
await waitFor(() => E(S.getByText("Ok")).toBeInTheDocument());
window.dispatchEvent(new StorageEvent("storage", { key: k, newValue: v }));
if (exp) await waitFor(() => E(pushMock).toHaveBeenCalledWith(exp)); else E(pushMock).not.toHaveBeenCalled();
},
);
// AC-identity.fe-auth.13 AC-identity.fe-auth.14 AC-meta.fe-ia-nav.14 AC22.15.3 EPIC-022 EPIC-023
