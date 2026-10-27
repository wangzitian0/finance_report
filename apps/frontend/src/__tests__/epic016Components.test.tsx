import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderReviewComponent } from "./helpers/renderReviewComponent";
import { PdfPreviewPane, TransactionTable, ConflictResolutionDialog } from "@/components/review/StatementReview";
import { BottomTabBar } from "@/components/shell/BottomTabBar";

// Mock next/navigation
vi.mock("next/navigation", () => ({
    usePathname: () => "/dashboard",
    useRouter: () => ({
        push: vi.fn(),
        replace: vi.fn(),
    }),
}));

const mockedDownload = vi.fn();
vi.mock("@/lib/api-client", () => ({
    apiOperation: vi.fn(),
    apiOperationDownload: (...args: unknown[]) => mockedDownload(...args),
}));

describe("EPIC-016 Componentization Tests", () => {
    // AC-extraction.fe-stage1-review.12
    it("mounts PdfPreviewPane and asserts primary affordance (AC16.23.6)", () => {
        renderReviewComponent(<PdfPreviewPane statementId={null} />);
        expect(screen.getByText("PDF Preview")).toBeInTheDocument();
    });

    it("AC16.33.5 embeds the document as a same-origin blob URL without sandbox and cleans up on unmount", async () => {
        mockedDownload.mockResolvedValueOnce({ blob: new Blob(["%PDF-1.4"]), filename: "f.pdf" });
        URL.createObjectURL = vi.fn(() => "blob:preview-1");
        URL.revokeObjectURL = vi.fn();

        const { unmount } = renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument />);
        const iframe = await screen.findByTitle("Statement PDF preview");
        expect(mockedDownload).toHaveBeenCalledWith(
            "get_statement_document_statements__statement_id__document_get",
            { path: { statement_id: "s1" } },
        );
        expect(iframe).toHaveAttribute("src", "blob:preview-1");
        expect(iframe).not.toHaveAttribute("sandbox");
        expect(iframe).toHaveAttribute("referrerPolicy", "no-referrer");
        unmount();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
    });

    it("AC16.33.5 shows a fallback when no document exists and surfaces fetch error", async () => {
        mockedDownload.mockClear();
        renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument={false} />);
        expect(mockedDownload).not.toHaveBeenCalled();
        expect(screen.getByText("PDF preview not available")).toBeInTheDocument();

        mockedDownload.mockRejectedValueOnce(new Error("502 Bad Gateway"));
        renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument />);
        expect(await screen.findByText("PDF preview could not be loaded")).toBeInTheDocument();
    });

    it("mounts TransactionTable and asserts primary affordance (AC16.23.6)", () => {
        const transactions = [
            {
                id: "1",
                statement_id: "stmt_1",
                txn_date: "2024-01-01",
                description: "Test Txn",
                amount: "100.0",
                direction: "OUT",
                reference: null,
                currency: "SGD",
                balance_after: null,
                status: "pending" as const,
                confidence: "high" as const,
                created_at: "2024-01-01T00:00:00Z",
                updated_at: "2024-01-01T00:00:00Z"
            }
        ];
        renderReviewComponent(
            <TransactionTable
                transactions={transactions}
                currency="SGD"
            />
        );
        expect(screen.getAllByText("Test Txn").length).toBeGreaterThan(0);
        expect(screen.getAllByText("high").length).toBeGreaterThan(0);
    });

    it("mounts ConflictResolutionDialog and asserts primary affordance (AC16.23.6)", () => {
        renderReviewComponent(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={() => {}}
                duplicateCandidates={[]}
                transferPairCandidates={[]}
            />
        );
        expect(screen.getByText("Resolve Conflicts")).toBeInTheDocument();
        expect(screen.getByText("No conflicts detected for this statement.")).toBeInTheDocument();
    });

    it("mounts BottomTabBar and asserts primary affordance (AC16.23.6)", () => {
        renderReviewComponent(<BottomTabBar />);
        expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
        expect(screen.getByText("Home")).toBeInTheDocument();
    });
});
