import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import SettingsPage from "@/app/(main)/settings/page";
const nav = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));
const replaceMock = vi.fn(), S = screen, E = expect, tab = (n: string) => S.getByRole("tab", { name: n });
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.searchParams, useRouter: () => ({ replace: replaceMock }) }));
vi.mock("@/components/settings/SettingsPanels", () => ({
GeneralSettingsPanel: () => <div data-testid="general-settings" />, AiSettingsPanel: () => <div data-testid="ai-settings" />,
AccountsPanel: () => <div data-testid="accounts-settings" />,
}));
beforeEach(() => { nav.searchParams = new URLSearchParams(); replaceMock.mockReset(); });
it("EPIC-022 AC22.21.4 tabs, ARIA, keyboard nav", () => {
render(<SettingsPage />);
const gen = tab("General");
E(gen).toHaveAttribute("aria-selected", "true");
E(gen).toHaveAttribute("aria-controls", "settings-panel-general");
E(S.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "settings-tab-general");
E(S.getByTestId("general-settings")).toBeInTheDocument();
E(S.queryByTestId("ai-settings")).toBeNull();
E(S.getAllByRole("tab").map((t) => t.textContent)).toEqual(["General", "AI", "Accounts"]);
fireEvent.click(tab("AI"));
E(S.getByTestId("ai-settings")).toBeInTheDocument();
E(replaceMock).toHaveBeenCalledWith("/settings?tab=ai", { scroll: false });
fireEvent.click(gen);
const list = S.getByRole("tablist", { name: "Settings sections" });
fireEvent.keyDown(list, { key: "ArrowRight" });
E(tab("AI")).toHaveAttribute("aria-selected", "true");
E(tab("AI")).toHaveFocus();
fireEvent.keyDown(list, { key: "ArrowLeft" });
E(gen).toHaveAttribute("aria-selected", "true");
});
it.each([["ai", "AI", "ai-settings"], ["accounts", "Accounts", "accounts-settings"]] as const)("AC-ledger.fe-accounts-tab.1 ?tab=%s", (q, name, tid) => {
nav.searchParams = new URLSearchParams(`tab=${q}`);
render(<SettingsPage />);
E(tab(name)).toHaveAttribute("aria-selected", "true");
E(S.getByTestId(tid)).toBeInTheDocument();
E(S.queryByTestId("general-settings")).toBeNull();
E(S.queryByRole("link", { name: /Chart of Accounts/i })).toBeNull();
if (q === "accounts") {
fireEvent.click(tab("General"));
E(S.queryByTestId("accounts-settings")).toBeNull();
fireEvent.click(tab("Accounts"));
E(replaceMock).toHaveBeenLastCalledWith("/settings?tab=accounts", { scroll: false });
}
});
it("AC22.21.4 the retired ?tab=llm opens General", () => {
nav.searchParams = new URLSearchParams("tab=llm");
render(<SettingsPage />);
E(tab("General")).toHaveAttribute("aria-selected", "true");
E(S.getByTestId("general-settings")).toBeInTheDocument();
E(S.queryByRole("tab", { name: "LLM Models" })).toBeNull();
});
it("AC22.21.4 the Portfolio Holdings link points at /portfolio", () => {
render(<SettingsPage />);
E(S.getByRole("link", { name: "Portfolio Holdings" })).toHaveAttribute("href", "/portfolio");
});
