import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";

describe("ConflictResolutionDialog", () => {
    const onClose = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows empty state when no candidates and closes on overlay and Close button", () => {
        render(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={onClose}
                duplicateCandidates={[]}
                transferPairCandidates={[]}
            />
        );

        expect(screen.getByText("No conflicts detected for this statement.")).toBeInTheDocument();

        // click the overlay background -> should call onClose
        const overlay = document.querySelector(".fixed.inset-0 > .absolute");
        if (overlay) fireEvent.click(overlay);
        expect(onClose).toHaveBeenCalled();

        // Close button in footer - pick the button that has visible text 'Close'
        const closeButtons = screen.getAllByRole("button", { name: /Close/i });
        const footerClose = closeButtons.find((b) => b.textContent?.trim() === "Close");
        expect(footerClose).toBeDefined();
        fireEvent.click(footerClose!);
        expect(onClose).toHaveBeenCalledTimes(2);
    });

    it("renders duplicate and transfer candidates with action buttons", () => {
        const dup = [{ description: "Dup One", txn_date: "2024-01-01", amount: "10.00" }];
        const transfer = [{ description: "Transfer A", txn_date: "2024-01-02", amount: "20.00" }];

        render(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={onClose}
                duplicateCandidates={dup}
                transferPairCandidates={transfer}
            />
        );

        expect(screen.getByText("Duplicate Candidates")).toBeInTheDocument();
        expect(screen.getByText("Dup One")).toBeInTheDocument();
        expect(screen.getByText("Transfer Pair Candidates")).toBeInTheDocument();
        expect(screen.getByText("Transfer A")).toBeInTheDocument();

        // action buttons present
        expect(screen.getAllByText("Resolve").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Link Pair").length).toBeGreaterThanOrEqual(1);
    });
});
