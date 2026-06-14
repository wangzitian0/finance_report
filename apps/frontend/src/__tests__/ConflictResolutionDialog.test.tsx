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
        const dup = [{ id: "txn-dup-1", description: "Dup One", txn_date: "2024-01-01", amount: "10.00" }];
        const transfer = [{ id: "txn-transfer-1", description: "Transfer A", txn_date: "2024-01-02", amount: "20.00" }];

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

    it("AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action", () => {
        const onResolve = vi.fn();
        render(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={onClose}
                duplicateCandidates={[{ id: "txn-dup-1", description: "Dup One", txn_date: "2024-01-01", amount: "10.00" }]}
                transferPairCandidates={[{ id: "txn-transfer-1", description: "Transfer A", txn_date: "2024-01-02", amount: "20.00" }]}
                onResolve={onResolve}
            />
        );

        fireEvent.click(screen.getByText("Resolve"));
        expect(onResolve).toHaveBeenCalledWith("confirm_distinct");

        fireEvent.click(screen.getByText("Link Pair"));
        expect(onResolve).toHaveBeenCalledWith("link_transfer");
    });

    it("AC16.34.3 disables the action buttons while a resolution is in flight", () => {
        const onResolve = vi.fn();
        render(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={onClose}
                duplicateCandidates={[{ id: "txn-dup-1", description: "Dup One", txn_date: "2024-01-01", amount: "10.00" }]}
                transferPairCandidates={[]}
                onResolve={onResolve}
                isResolving
            />
        );

        const resolving = screen.getByText("Resolving…");
        expect(resolving).toBeDisabled();
        fireEvent.click(resolving);
        expect(onResolve).not.toHaveBeenCalled();
    });
});
