import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConflictResolutionDialog } from "@/components/review/ConflictResolutionDialog";

describe("ConflictResolutionDialog - keyboard", () => {
    const onClose = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("calls onClose when Escape pressed inside dialog", () => {
        render(
            <ConflictResolutionDialog
                isOpen={true}
                onClose={onClose}
                duplicateCandidates={[]}
                transferPairCandidates={[]}
            />
        );

        const dialog = screen.getByRole("dialog");
        fireEvent.keyDown(dialog, { key: "Escape" });
        expect(onClose).toHaveBeenCalled();
    });
});
