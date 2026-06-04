import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { MobileNav } from "@/components/MobileNav";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

let pathnameMock = "/dashboard";

vi.mock("next/navigation", () => ({
    usePathname: () => pathnameMock,
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("MobileNav coverage (AC16.23.6)", () => {
    beforeEach(() => {
        pathnameMock = "/dashboard";
    });

    it("AC19.6.4 opens workflow mobile nav, exposes Advanced drill-downs, and closes via link click", () => {
        renderReviewComponent(<MobileNav />);
        const trigger = screen.getByLabelText("Open navigation menu");
        fireEvent.click(trigger);
        const uploadLink = screen.getByRole("link", { name: /upload/i });
        expect(uploadLink).toHaveAttribute("href", "/dashboard");
        expect(screen.getByRole("link", { name: /events/i })).toHaveAttribute("href", "/events");
        expect(screen.getByRole("link", { name: /reports/i })).toHaveAttribute("href", "/reports");
        expect(screen.getByRole("link", { name: /portfolio/i })).toHaveAttribute("href", "/portfolio");
        expect(screen.queryByRole("link", { name: /accounts/i })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: /advanced/i })).toBeInTheDocument();
        expect(uploadLink.className).toContain("accent-muted");

        fireEvent.click(screen.getByRole("button", { name: /advanced/i }));
        expect(screen.getByRole("link", { name: /statements/i })).toHaveAttribute("href", "/statements");
        expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute("href", "/review");
        expect(screen.getByRole("link", { name: /accounts/i })).toHaveAttribute("href", "/accounts");
        expect(screen.getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
        expect(screen.getByRole("link", { name: /reconciliation/i })).toHaveAttribute("href", "/reconciliation");
        expect(screen.getByRole("link", { name: /processing/i })).toHaveAttribute("href", "/processing");
        expect(screen.getByRole("link", { name: /ai settings/i })).toHaveAttribute("href", "/chat");

        const closeBtn = screen.getByText("Close panel").closest("button")!;
        fireEvent.click(closeBtn);
        expect(screen.queryByRole("link", { name: /upload/i })).not.toBeInTheDocument();

        fireEvent.click(screen.getByLabelText("Open navigation menu"));
        fireEvent.click(screen.getByRole("button", { name: /advanced/i }));
        fireEvent.click(screen.getByRole("link", { name: /review/i }));
        expect(screen.queryByRole("link", { name: /review/i })).not.toBeInTheDocument();
    });

    it("AC19.6.4 highlights active advanced routes in mobile navigation", () => {
        pathnameMock = "/review/run/run-1";
        renderReviewComponent(<MobileNav />);

        fireEvent.click(screen.getByLabelText("Open navigation menu"));
        const advancedButton = screen.getByRole("button", { name: /advanced/i });
        expect(advancedButton.className).toContain("accent-muted");
        fireEvent.click(advancedButton);
        const reviewLink = screen.getByRole("link", { name: /review/i });
        expect(reviewLink.className).toContain("accent-muted");
    });
});
