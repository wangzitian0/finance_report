import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderReviewComponent } from "./helpers/renderReviewComponent";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { TransactionTable } from "@/components/review/TransactionTable";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";
import { MobileNav } from "@/components/MobileNav";

// Mock next/navigation
vi.mock("next/navigation", () => ({
    usePathname: () => "/dashboard",
    useRouter: () => ({
        push: vi.fn(),
        replace: vi.fn(),
    }),
}));

describe("EPIC-016 Componentization Tests", () => {
    it("mounts PdfPreviewPane and asserts primary affordance (AC16.23.6)", () => {
        renderReviewComponent(<PdfPreviewPane pdfUrl="https://example.com/test.pdf" />);
        expect(screen.getByTitle("Statement PDF preview")).toBeInTheDocument();
    });

    it("mounts TransactionTable and asserts primary affordance (AC16.23.6)", () => {
        const transactions = [
            {
                id: "1",
                statement_id: "stmt_1",
                txn_date: "2024-01-01",
                description: "Test Txn",
                amount: 100.0,
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
                onEdit={() => {}}
                pendingEdits={new Map()}
                onSave={() => {}}
                onDiscard={() => {}}
                actionLoading={false}
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

    it("mounts MobileNav and asserts primary affordance (AC16.23.6)", () => {
        renderReviewComponent(<MobileNav />);
        expect(screen.getByLabelText("Open navigation menu")).toBeInTheDocument();
    });
});
