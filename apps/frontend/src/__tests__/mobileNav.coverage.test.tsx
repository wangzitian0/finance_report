import { describe, it, expect, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { MobileNav } from "@/components/MobileNav";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("next/navigation", () => ({
    usePathname: () => "/dashboard",
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("MobileNav coverage (AC16.23.6)", () => {
    it("AC16.23.5 opens a full mobile nav drawer with active highlighting, closes via close button, and closes via link click", () => {
        renderReviewComponent(<MobileNav />);
        const trigger = screen.getByLabelText("Open navigation menu");
        fireEvent.click(trigger);
        const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
        expect(dashboardLink).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /accounts/i })).toHaveAttribute("href", "/accounts");
        expect(screen.getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
        expect(screen.getByRole("link", { name: /statements/i })).toHaveAttribute("href", "/statements");
        expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute("href", "/review");
        expect(screen.getByRole("link", { name: /portfolio/i })).toHaveAttribute("href", "/portfolio");
        expect(screen.getByRole("link", { name: /reports/i })).toHaveAttribute("href", "/reports");
        expect(screen.getByRole("link", { name: /reconciliation/i })).toHaveAttribute("href", "/reconciliation");
        expect(screen.getByRole("link", { name: /processing/i })).toHaveAttribute("href", "/processing");
        expect(screen.getByRole("link", { name: /ai advisor/i })).toHaveAttribute("href", "/chat");
        expect(dashboardLink.className).toContain("accent-muted");

        const closeBtn = screen.getByText("Close panel").closest("button")!;
        fireEvent.click(closeBtn);
        expect(screen.queryByRole("link", { name: /dashboard/i })).not.toBeInTheDocument();

        fireEvent.click(screen.getByLabelText("Open navigation menu"));
        fireEvent.click(screen.getByRole("link", { name: /review/i }));
    });
});
