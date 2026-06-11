import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ReviewActionBar } from "@/components/review/ReviewActionBar";

describe("ReviewActionBar in-place unblock (EPIC-022 AC22.5.2)", () => {
    const baseProps = {
        onApprove: vi.fn(),
        onReject: vi.fn(),
        actionLoading: false,
        balanceValid: true,
    };

    it("AC22.5.2 enables Approve and shows no blocker when nothing is wrong", () => {
        render(<ReviewActionBar {...baseProps} />);
        expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
        expect(screen.queryByText(/Approve is paused/i)).not.toBeInTheDocument();
    });

    it("AC22.5.2 explains a balance block and offers in-place re-parse", () => {
        const onReparse = vi.fn();
        render(<ReviewActionBar {...baseProps} balanceValid={false} onReparse={onReparse} />);

        expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
        expect(screen.getByText(/Approve is paused/i)).toBeInTheDocument();
        expect(screen.getByText(/closing balance doesn't match/i)).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /Re-parse statement/i }));
        expect(onReparse).toHaveBeenCalledTimes(1);
    });

    it("AC22.5.2 explains a conflict block and offers to open the resolver", () => {
        const onResolveConflicts = vi.fn();
        render(
            <ReviewActionBar
                {...baseProps}
                approvalBlockedReason="Resolve duplicate and transfer-pair candidates before approval"
                onResolveConflicts={onResolveConflicts}
            />,
        );

        expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
        expect(screen.getByText(/duplicate or transfer-pair/i)).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /Resolve conflicts/i }));
        expect(onResolveConflicts).toHaveBeenCalledTimes(1);
    });
});
