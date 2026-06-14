import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import ReviewPage from "@/app/(main)/review/page";
import { apiFetch } from "@/lib/api";

import { renderReviewComponent } from "./helpers/renderReviewComponent";

// #1001 / AC16.36: the dedicated /review surface is a first-class Stage-2 review
// destination, independent of the reconciliation workbench it used to nest under.
vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
    usePathname: vi.fn(() => "/review"),
}));

const mockedApi = vi.mocked(apiFetch);

const queueData = {
    pending_matches: [
        {
            id: "m1",
            // Decimal fields serialize as strings (the MoneyValue decimal-string
            // contract / generated api-types), so the mock mirrors the wire shape.
            match_score: "88",
            status: "pending_review",
            created_at: "2024-01-03T00:00:00Z",
            description: "Salary transfer",
            amount: "20",
            txn_date: "2024-01-03",
            confidence_tier: "HIGH",
        },
    ],
    consistency_checks: [],
    has_unresolved_checks: false,
};

describe("dedicated /review surface (#1001)", () => {
    beforeEach(() => {
        mockedApi.mockReset();
        mockedApi.mockImplementation((path: string) => {
            if (path.startsWith("/api/statements/stage2/queue")) {
                return Promise.resolve(queueData as never);
            }
            if (path === "/api/accounts/processing/summary") {
                return Promise.resolve({
                    pending_count: 0,
                    pending_total: "0",
                    currency: "SGD",
                    oldest_pending_date: null,
                } as never);
            }
            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [] } as never);
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });
    });

    it("AC16.36.1 renders the Stage-2 review queue as a standalone page", async () => {
        renderReviewComponent(<ReviewPage />);

        expect(await screen.findByText("Review queue")).toBeInTheDocument();
        // The description renders in both the desktop table and mobile card views.
        await waitFor(() => expect(screen.getAllByText("Salary transfer").length).toBeGreaterThan(0));
    });

    it("AC16.36.2 loads the global queue (no run filter) on the dedicated route", async () => {
        renderReviewComponent(<ReviewPage />);

        await waitFor(() => {
            // Pathname is /review (not /review/run/<id>), so the global, unfiltered
            // queue endpoint is hit — review is no longer scoped to a single run.
            const queueCall = mockedApi.mock.calls.find((call) =>
                String(call[0]).startsWith("/api/statements/stage2/queue")
            );
            expect(queueCall).toBeDefined();
            expect(String(queueCall?.[0])).not.toContain("run_id");
        });
    });
});
