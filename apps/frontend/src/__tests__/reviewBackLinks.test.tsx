import type { ReactNode } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { BackLink } from "@/components/ui/SmartBackLink";
import { AiSuggestionsQueue } from "@/components/audit/AiSuggestionsQueue";
import { apiOperation } from "@/lib/api-client";

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

vi.mock("@/lib/api-client", () => ({
    apiOperation: vi.fn(),
}));

vi.mock("next/navigation", () => ({
    useSearchParams: () => navigationState.searchParams,
}));

describe("Review surfaces back-link + plain copy (EPIC-022 AC22.5.3, AC22.5.4)", () => {
    beforeEach(() => {
        vi.mocked(apiOperation).mockReset();
        navigationState.searchParams = new URLSearchParams();
    });

    // AC-platform.fe-ia-inbox.4
    it("AC22.5.3 BackLink defaults to the notification center", () => {
        render(<BackLink>Back to Notifications</BackLink>);
        expect(screen.getByRole("link", { name: /Back to Notifications/i })).toHaveAttribute(
            "href",
            "/notifications",
        );
    });

    it("the AI suggestion queue shows the empty state when the response has no items field", async () => {
        vi.mocked(apiOperation).mockResolvedValue({} as any);
        render(<AiSuggestionsQueue />);
        expect(await screen.findByText("No pending AI suggestions")).toBeInTheDocument();
    });

    it("the AI suggestion queue shows a back-link only when the caller passes return_to", async () => {
        vi.mocked(apiOperation).mockResolvedValue({ items: [] } as any);
        render(<AiSuggestionsQueue />);
        await waitFor(() => expect(screen.getByText("Suggestions to review")).toBeInTheDocument());
        expect(screen.queryByRole("link")).not.toBeInTheDocument();
    });

    it("AC22.11.3 BackLink returns attention-origin users to the attention queue", () => {
        navigationState.searchParams = new URLSearchParams("from=attention");

        render(<BackLink>Back to Notifications</BackLink>);

        expect(screen.getByRole("link", { name: /Back to Needs Confirmation/i })).toHaveAttribute(
            "href",
            "/audit",
        );
    });

    // AC-platform.fe-ia-inbox.5
    it("AC22.5.4 the review surface heading uses plain language, not internal jargon", async () => {
        vi.mocked(apiOperation).mockResolvedValue({ items: [] } as any);
        render(<AiSuggestionsQueue />);
        await waitFor(() => expect(screen.getByText("Suggestions to review")).toBeInTheDocument());
        expect(screen.queryByText(/Stage 2/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/60-84 score band/i)).not.toBeInTheDocument();
    });

    it("forwards statement_id query parameter and honors safe internal return_to in BackLink", async () => {
        navigationState.searchParams = new URLSearchParams(
            "statement_id=s1&return_to=%2Fstatements%2Fs1%2Freview",
        );
        vi.mocked(apiOperation).mockResolvedValue({ items: [] } as any);

        render(<AiSuggestionsQueue />);

        await waitFor(() =>
            expect(vi.mocked(apiOperation)).toHaveBeenCalledWith(
                "list_ai_suggestions_ai_suggestions_get",
                { query: { statement_id: "s1" } },
            ),
        );
        expect(
            screen.getByRole("link", { name: /Back to Statement Review/i }),
        ).toHaveAttribute("href", "/statements/s1/review");
    });
});
