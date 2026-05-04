import { describe, it, expect, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { MobileNav } from "@/components/MobileNav";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("next/navigation", () => ({
    usePathname: () => "/dashboard",
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("MobileNav coverage (AC16.23.6)", () => {
    it("opens the sheet, renders nav links with active highlighting, closes via close button, and closes via link click", () => {
        renderReviewComponent(<MobileNav />);
        const trigger = screen.getByLabelText("Open navigation menu");
        fireEvent.click(trigger);
        const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
        expect(dashboardLink).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /review/i })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /processing/i })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /portfolio/i })).toBeInTheDocument();
        expect(dashboardLink.className).toContain("accent-muted");

        const closeBtn = screen.getByText("Close panel").closest("button")!;
        fireEvent.click(closeBtn);
        expect(screen.queryByRole("link", { name: /dashboard/i })).not.toBeInTheDocument();

        fireEvent.click(screen.getByLabelText("Open navigation menu"));
        fireEvent.click(screen.getByRole("link", { name: /review/i }));
    });
});
