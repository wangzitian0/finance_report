import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);

describe("Statement review page", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows error fallback when fetch fails", async () => {
        mockedApi.mockRejectedValueOnce(new Error("network fail"));
        // pending statements query fallback
        mockedApi.mockResolvedValueOnce({ items: [] });

        renderReviewComponent(<StatementReviewPage /> as any);

        expect(await screen.findByText("Failed to load statement")).toBeInTheDocument();
        expect(await screen.findByText("Retry")).toBeInTheDocument();
        expect(await screen.findByText("network fail")).toBeInTheDocument();
    });

    it("disables Approve when balance validation fails", async () => {
        const stmtFail = {
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
            balance_validation_result: { opening_match: true, closing_match: false, calculated_closing: "0" },
            pdf_url: null,
            transactions: [],
        };

        mockedApi.mockResolvedValueOnce(stmtFail);
        mockedApi.mockResolvedValueOnce({ items: [{ id: "s1" }] });

        renderReviewComponent(<StatementReviewPage /> as any);

        const approveBtn = await screen.findByRole("button", { name: "Approve" });
        expect(approveBtn).toBeDisabled();
    });

    it("enables Approve when balance validation passes", async () => {
        const stmtOK = {
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

        mockedApi.mockResolvedValueOnce(stmtOK);
        mockedApi.mockResolvedValueOnce({ items: [{ id: "s1" }] });

        renderReviewComponent(<StatementReviewPage /> as any);

        const approveBtn = await screen.findByRole("button", { name: "Approve" });
        expect(approveBtn).toBeEnabled();
    });
});
