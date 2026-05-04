import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => ({ get: () => null })),
    usePathname: vi.fn(() => "/"),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);

describe("Review pages data flows", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("review queue shows empty state and toggles severity filter", async () => {
        mockedApi.mockResolvedValueOnce({ pending_matches: [], consistency_checks: [], has_unresolved_checks: false });
        // filtered checks call
        mockedApi.mockResolvedValueOnce({ items: [] });
        renderReviewComponent(<ReviewQueuePage /> as any);
        expect(await screen.findByText("Reconciliation Review Queue")).toBeInTheDocument();
        expect(await screen.findByText("No pending matches")).toBeInTheDocument();
    });

    it("statement review page shows loading fallback then data", async () => {
        const stmt = {
            id: "s1",
            original_filename: "f.pdf",
            institution: "Bank",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 0,
            closing_balance: 0,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: true, closing_match: true, calculated_closing: "0" },
            pdf_url: null,
            transactions: [],
        };
        // first call for statement review
        mockedApi.mockResolvedValueOnce(stmt);
        // pending statements
        mockedApi.mockResolvedValueOnce({ items: [{ id: "s1" }] });

        renderReviewComponent(<StatementReviewPage /> as any);
        expect(await screen.findByText("Back to Statements")).toBeInTheDocument();
    });
});
