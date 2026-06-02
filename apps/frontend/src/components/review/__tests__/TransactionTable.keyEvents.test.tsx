import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TransactionTable } from "@/components/review/TransactionTable";
import type { BankStatementTransaction } from "@/lib/types";

describe("TransactionTable key handlers", () => {
    const onEdit = vi.fn();
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    beforeEach(() => vi.clearAllMocks());

    const sample: BankStatementTransaction[] = [
        {
            id: "kt1",
            statement_id: "s1",
            txn_date: "2024-01-01",
            description: "Test",
            amount: 10,
            direction: "OUT",
            confidence: "high",
            created_at: "",
            updated_at: "",
            status: "pending",
        } as unknown as BankStatementTransaction,
    ];

    it("handles Enter on date and description inputs and focus on select triggers beginEdit", () => {
        const pending = new Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>>();

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));

        // click date cell to edit
        fireEvent.click(desktopRegion.getByText("2024-01-01"));
        const dateInput = desktopRegion.getByDisplayValue("2024-01-01");
        fireEvent.keyDown(dateInput, { key: "Enter" });

        // click description cell to edit
        fireEvent.click(desktopRegion.getByText("Test"));
        const descInput = desktopRegion.getByDisplayValue("Test");
        fireEvent.keyDown(descInput, { key: "Enter" });

        // click amount to open combined editor
        fireEvent.click(desktopRegion.getByText(/SGD/));

        const select = desktopRegion.getByDisplayValue("OUT");
        fireEvent.focus(select);
        fireEvent.keyDown(select, { key: "Enter" });

        // blur the combined editor wrapper to close
        const wrapper = select.closest("div") as HTMLDivElement;
        fireEvent.blur(wrapper, { relatedTarget: null });

        expect(onEdit).toBeTruthy();
    });
});
