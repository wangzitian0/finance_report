import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { TransactionTable } from "@/components/review/TransactionTable";
import type { BankStatementTransaction } from "@/lib/types";

describe("TransactionTable (read-only rendering)", () => {
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

    it("renders transaction fields as static text with no editable inputs", () => {
        render(<TransactionTable transactions={sample} currency="SGD" />);

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        expect(desktopRegion.getByText("2024-01-01")).toBeInTheDocument();
        expect(desktopRegion.getByText("Test")).toBeInTheDocument();
        // Read-only: no inline editors are rendered.
        expect(screen.queryByRole("textbox")).toBeNull();
        expect(screen.queryByRole("combobox")).toBeNull();
    });
});
