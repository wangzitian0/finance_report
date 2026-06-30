import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { BottomTabBar } from "@/components/shell/BottomTabBar";

const pushMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("next/navigation", () => ({
    usePathname: () => "/",
    useRouter: () => ({ push: pushMock, replace: vi.fn(), refresh: refreshMock }),
}));

let authed = false;
vi.mock("@/lib/auth", () => ({
    isAuthenticated: () => authed,
}));

// AddSheet pulls heavy uploader/evidence components; stub it so this suite stays
// focused on the tab bar's structure and the Add action wiring.
vi.mock("@/components/shell/AddSheet", () => ({
    default: ({ isOpen, onUploadComplete }: { isOpen: boolean; onUploadComplete?: () => void }) =>
        isOpen ? (
            <div data-testid="add-sheet">
                <button data-testid="add-complete" onClick={() => onUploadComplete?.()}>
                    complete
                </button>
            </div>
        ) : null,
}));

describe("BottomTabBar (EPIC-022 AC22.21.2)", () => {
    beforeEach(() => {
        pushMock.mockClear();
        refreshMock.mockClear();
    });

    it("renders only Home when unauthenticated", () => {
        authed = false;
        render(<BottomTabBar />);
        expect(screen.getByText("Home")).toBeInTheDocument();
        expect(screen.queryByText("Chat")).toBeNull();
        expect(screen.queryByText("Audit")).toBeNull();
        expect(screen.queryByText("More")).toBeNull();
        expect(screen.queryByLabelText("Add")).toBeNull();
    });

    it("exposes the five-target bar plus a center Add action when authenticated", () => {
        authed = true;
        render(<BottomTabBar />);
        expect(screen.getByText("Home")).toBeInTheDocument();
        expect(screen.getByText("Chat")).toBeInTheDocument();
        expect(screen.getByText("Audit")).toBeInTheDocument();
        expect(screen.getByText("More")).toBeInTheDocument();

        // The center Add is an action that opens a sheet, not a route.
        expect(screen.queryByTestId("add-sheet")).toBeNull();
        fireEvent.click(screen.getByLabelText("Add"));
        expect(screen.getByTestId("add-sheet")).toBeInTheDocument();

        // A completed upload refreshes the current route so new data shows.
        fireEvent.click(screen.getByTestId("add-complete"));
        expect(refreshMock).toHaveBeenCalledTimes(1);
    });

    it("points each tab at its canonical route", () => {
        authed = true;
        render(<BottomTabBar />);
        expect(screen.getByText("Home").closest("a")).toHaveAttribute("href", "/");
        expect(screen.getByText("Chat").closest("a")).toHaveAttribute("href", "/chat");
        expect(screen.getByText("Audit").closest("a")).toHaveAttribute("href", "/audit");
        expect(screen.getByText("More").closest("a")).toHaveAttribute("href", "/more");
    });
});
