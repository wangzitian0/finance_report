import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import RootLayout, { metadata, viewport } from "@/app/layout";
import { analyticsClientIdMissingInDeployedEnv } from "@/lib/analytics-env";
vi.mock("next/font/google", () => ({ Inter: () => ({ variable: "--font-inter" }) }));
vi.mock("@/components/RootClients", () => ({ AuthGuard: ({ children }: { children: ReactNode }) => <div data-testid="ag">{children}</div>, Analytics: () => <div data-testid="an" /> }));
vi.mock("@/app/providers", () => ({ Providers: ({ children }: { children: ReactNode }) => <div data-testid="pr">{children}</div> }));
it("AC16.17.5 AC16.25.4 Infra-014 C5 RootLayout + analytics env", () => {
const err = vi.spyOn(console, "error").mockImplementation(() => {}), prevUrl = process.env.NEXT_PUBLIC_APP_URL, prevId = process.env.OPENPANEL_CLIENT_ID;
process.env.NEXT_PUBLIC_APP_URL = "https://report.zitian.party";
delete process.env.OPENPANEL_CLIENT_ID;
try {
const r1 = render(<RootLayout><div>Root Child</div></RootLayout>);
expect(screen.getByTestId("pr")).toBeInTheDocument();
expect(screen.getByTestId("ag")).toBeInTheDocument();
expect(screen.getByText("Root Child")).toBeInTheDocument();
r1.unmount();
render(<RootLayout><div>b</div></RootLayout>);
const openPanelErrs = err.mock.calls.filter(([m]) => String(m).includes("OPENPANEL_CLIENT_ID is empty"));
expect(openPanelErrs).toHaveLength(1);
} finally {
err.mockRestore();
if (prevUrl === undefined) delete process.env.NEXT_PUBLIC_APP_URL; else process.env.NEXT_PUBLIC_APP_URL = prevUrl;
if (prevId === undefined) delete process.env.OPENPANEL_CLIENT_ID; else process.env.OPENPANEL_CLIENT_ID = prevId;
}
expect([metadata.appleWebApp, metadata.other, viewport.themeColor, "themeColor" in metadata]).toEqual([{ capable: true, title: "Finance Report", statusBarStyle: "default" }, { "mobile-web-app-capable": "yes" }, "#7c3aed", false]);
for (const [id, u, exp] of [[undefined, "https://report.zitian.party", true], ["", "https://report-staging.zitian.party", true], [undefined, "https://report-pr-7.zitian.party", false], [undefined, "http://localhost:3000", false], [undefined, undefined, false], ["abc-123", "https://report.zitian.party", false]] as const) expect(analyticsClientIdMissingInDeployedEnv(id, u)).toBe(exp);
});
// AC-meta.fe-app-shell.21 AC-meta.fe-app-shell.6
