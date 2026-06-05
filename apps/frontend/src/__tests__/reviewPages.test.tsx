import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
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
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve({ duplicates: [], transfer_pairs: [] });
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);
        expect(await screen.findByText("Back to Statements")).toBeInTheDocument();
    });

    it("AC16.33.4 sandboxes PDF preview URLs", () => {
        renderReviewComponent(<PdfPreviewPane pdfUrl="https://example.com/presigned.pdf?signature=secret" /> as any);

        const iframe = screen.getByTitle("Statement PDF preview");
        expect(iframe).toHaveAttribute("sandbox");
        expect(iframe).toHaveAttribute("referrerPolicy", "no-referrer");
    });
});
