import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import SettingsPage from "@/app/(main)/settings/page";

const navigationState = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
    useSearchParams: () => navigationState.searchParams,
    useRouter: () => ({ replace: replaceMock }),
}));

vi.mock("@/app/(main)/settings/general/page", () => ({
    default: () => <div data-testid="general-settings">GeneralMock</div>,
}));
vi.mock("@/app/(main)/settings/ai/page", () => ({
    default: () => <div data-testid="ai-settings">AiMock</div>,
}));
vi.mock("@/app/(main)/settings/llm/page", () => ({
    default: () => <div data-testid="llm-settings">LlmMock</div>,
}));

describe("Merged Settings page (EPIC-022 AC22.21.4)", () => {
    beforeEach(() => {
        navigationState.searchParams = new URLSearchParams();
        replaceMock.mockReset();
    });

    it("renders General/AI/LLM as tabs and defaults to General", () => {
        render(<SettingsPage />);
        expect(screen.getByRole("tab", { name: "General" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("general-settings")).toBeInTheDocument();
        expect(screen.queryByTestId("ai-settings")).toBeNull();
    });

    it("switches to the AI and LLM tabs and syncs the ?tab= query for deep links", () => {
        render(<SettingsPage />);
        fireEvent.click(screen.getByRole("tab", { name: "AI" }));
        expect(screen.getByTestId("ai-settings")).toBeInTheDocument();
        expect(replaceMock).toHaveBeenCalledWith("/settings?tab=ai", { scroll: false });
        fireEvent.click(screen.getByRole("tab", { name: "LLM Models" }));
        expect(screen.getByTestId("llm-settings")).toBeInTheDocument();
        expect(replaceMock).toHaveBeenCalledWith("/settings?tab=llm", { scroll: false });
    });

    it("moves between tabs with the arrow keys (WAI-ARIA tabs pattern)", () => {
        render(<SettingsPage />);
        const tablist = screen.getByRole("tablist", { name: "Settings sections" });
        fireEvent.keyDown(tablist, { key: "ArrowRight" });
        expect(screen.getByRole("tab", { name: "AI" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByRole("tab", { name: "AI" })).toHaveFocus();
        expect(replaceMock).toHaveBeenCalledWith("/settings?tab=ai", { scroll: false });
        fireEvent.keyDown(tablist, { key: "ArrowLeft" });
        expect(screen.getByRole("tab", { name: "General" })).toHaveAttribute("aria-selected", "true");
    });

    it("wires each tab to its panel via aria-controls/labelledby", () => {
        render(<SettingsPage />);
        const tab = screen.getByRole("tab", { name: "General" });
        const panel = screen.getByRole("tabpanel");
        expect(tab).toHaveAttribute("aria-controls", "settings-panel-general");
        expect(panel).toHaveAttribute("aria-labelledby", "settings-tab-general");
    });

    it("opens the tab named by the ?tab= query (e.g. /settings/ai → ?tab=ai)", () => {
        navigationState.searchParams = new URLSearchParams("tab=ai");
        render(<SettingsPage />);
        expect(screen.getByRole("tab", { name: "AI" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("ai-settings")).toBeInTheDocument();
    });
});
