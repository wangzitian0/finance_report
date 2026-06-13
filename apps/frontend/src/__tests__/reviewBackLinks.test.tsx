import type { ReactNode } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { BackLink } from "@/components/ui/BackLink";
import AiSuggestionsPage from "@/app/(main)/review/ai-suggestions/page";
import { apiFetch } from "@/lib/api";

const navigationState = vi.hoisted(() => ({
    searchParams: new URLSearchParams(),
}));

vi.mock("next/link", () => ({
    __esModule: true,
    default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));

vi.mock("@/lib/api", () => ({
    apiFetch: vi.fn(),
}));

vi.mock("next/navigation", () => ({
    useSearchParams: () => navigationState.searchParams,
}));

describe("Review surfaces back-link + plain copy (EPIC-022 AC22.5.3, AC22.5.4)", () => {
    beforeEach(() => {
        vi.mocked(apiFetch).mockReset();
        navigationState.searchParams = new URLSearchParams();
    });

    it("AC22.5.3 BackLink defaults to the notification center", () => {
        render(<BackLink>Back to Notifications</BackLink>);
        expect(screen.getByRole("link", { name: /Back to Notifications/i })).toHaveAttribute(
            "href",
            "/notifications",
        );
    });

    it("AC22.5.3 the AI suggestion review surface offers a back-link to /notifications", async () => {
        vi.mocked(apiFetch).mockResolvedValue({ items: [] });
        render(<AiSuggestionsPage />);
        await waitFor(() =>
            expect(screen.getByRole("link", { name: /Back to Notifications/i })).toHaveAttribute(
                "href",
                "/notifications",
            ),
        );
    });

    it("AC22.11.3 BackLink returns attention-origin users to the attention queue", () => {
        navigationState.searchParams = new URLSearchParams("from=attention");

        render(<BackLink>Back to Notifications</BackLink>);

        expect(screen.getByRole("link", { name: /Back to Attention queue/i })).toHaveAttribute(
            "href",
            "/attention",
        );
    });

    it("AC22.5.4 the review surface heading uses plain language, not internal jargon", async () => {
        vi.mocked(apiFetch).mockResolvedValue({ items: [] });
        render(<AiSuggestionsPage />);
        await waitFor(() => expect(screen.getByText("Suggestions to review")).toBeInTheDocument());
        expect(screen.queryByText(/Stage 2/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/60-84 score band/i)).not.toBeInTheDocument();
    });
});
