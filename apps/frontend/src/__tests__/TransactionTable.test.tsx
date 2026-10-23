import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import * as money from "@/lib/audit/money";
import { TransactionTable } from "@/components/review/TransactionTable";
import type { BankStatementTransaction } from "@/lib/types";

describe("TransactionTable (read-only)", () => {
    const originalMatchMedia = window.matchMedia;

    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: originalMatchMedia,
        });
    });

    const sample: BankStatementTransaction[] = [
        {
            id: "t1",
            statement_id: "s1",
            txn_date: "2024-01-10",
            description: "Coffee",
            amount: "3.5",
            direction: "OUT",
            confidence: "high",
            created_at: "",
            updated_at: "",
            status: "pending",
        },
    ];

    it("renders transactions read-only without any inline edit inputs", () => {
        render(<TransactionTable transactions={sample} currency="SGD" />);

        expect(screen.getByText("Transactions")).toBeInTheDocument();
        expect(screen.getAllByText("Coffee").length).toBeGreaterThan(0);
        // No edit affordances should exist anymore.
        expect(screen.queryByRole("button", { name: /Approve Edits/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Discard/ })).toBeNull();
        expect(screen.queryByRole("textbox")).toBeNull();
        expect(screen.queryByRole("combobox")).toBeNull();
    });

    it("exposes a desktop transaction region that scrolls rows vertically and never horizontally", () => {
        render(<TransactionTable transactions={sample} currency="SGD" />);

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        // The card has a fixed height beside the PDF; rows past it must scroll (#2621), the sticky header stays.
        expect(region).toHaveClass("overflow-y-auto", "overflow-x-hidden");
        expect(region).not.toHaveClass("overflow-hidden");
        const table = region.querySelector("table");
        expect(table).toHaveClass("table-fixed", "border-collapse");
        expect(table).toHaveStyle({ width: "calc(100% - 4px)" });
    });

    it("reserves responsive margin when action column is rendered", () => {
        render(<TransactionTable transactions={sample} currency="SGD" onSelectTransaction={vi.fn()} />);

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        const table = region.querySelector("table");
        expect(table).toHaveStyle({ width: "calc(100% - 16px)" });
    });

    it("keeps mobile transaction cards in the DOM without matchMedia gating", () => {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: undefined,
        });

        render(<TransactionTable transactions={sample} currency="SGD" />);

        expect(screen.getByTestId("stage1-mobile-transaction-card-t1")).toBeInTheDocument();
        expect(screen.getAllByText("Coffee").length).toBeGreaterThan(0);
    });

    it("renders negative sign for OUT transactions", () => {
        render(<TransactionTable transactions={sample} currency="SGD" />);

        const negAmount = within(screen.getByTestId("stage1-desktop-transaction-region")).getByText(/-SGD/);
        expect(negAmount).toBeTruthy();
    });

    it("renders confidence badge classes correctly", () => {
        const three: BankStatementTransaction[] = [
            { ...sample[0], id: "a", confidence: "high" } as BankStatementTransaction,
            { ...sample[0], id: "b", confidence: "medium" } as BankStatementTransaction,
            { ...sample[0], id: "c", confidence: "low" } as BankStatementTransaction,
        ];

        render(<TransactionTable transactions={three} currency="SGD" />);

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const high = desktopRegion.getByText("high");
        const medium = desktopRegion.getByText("medium");
        const low = desktopRegion.getByText("low");

        expect(high.className).toContain("badge-success");
        expect(medium.className).toContain("badge-warning");
        expect(low.className).toContain("badge-error");
    });

    it("renders an empty table when transactions is nullish", () => {
        render(
            <TransactionTable
                transactions={undefined as unknown as BankStatementTransaction[]}
                currency="SGD"
            />,
        );

        expect(screen.getByText("Transactions")).toBeInTheDocument();
        expect(screen.getByText("0 total")).toBeInTheDocument();
        expect(
            within(screen.getByTestId("stage1-desktop-transaction-region")).queryByRole("row", {
                name: /SGD/,
            }),
        ).toBeNull();
    });

    it("prefers the confidence tier badge over the raw confidence label", () => {
        const tiered: BankStatementTransaction[] = [
            {
                ...sample[0],
                id: "tier-1",
                confidence: "low",
                confidence_tier: "HIGH",
            } as unknown as BankStatementTransaction,
        ];

        render(<TransactionTable transactions={tiered} currency="SGD" />);

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        // ConfidenceBadge branch is taken, so the raw confidence label is not rendered.
        expect(desktopRegion.queryByText("low")).toBeNull();
        expect(desktopRegion.getAllByText("HIGH").length).toBeGreaterThan(0);
    });

    it("calls formatCurrencyLocale for each transaction amount", () => {
        const spy = vi.spyOn(money, "formatCurrencyLocale");

        const mixed: BankStatementTransaction[] = [
            sample[0],
            {
                id: "t3",
                statement_id: "s1",
                txn_date: "2024-03-01",
                description: "Gift",
                amount: "50",
                direction: "IN",
                confidence: "high",
                created_at: "",
                updated_at: "",
                status: "pending",
            } as unknown as BankStatementTransaction,
        ];

        render(<TransactionTable transactions={mixed} currency="SGD" />);

        expect(spy).toHaveBeenCalled();
        const calls = spy.mock.calls.map((c) => c[0]);
        expect(calls.some((v) => v === "3.5" || v === 3.5)).toBe(true);
        expect(calls.some((v) => v === "50" || v === 50)).toBe(true);

        spy.mockRestore();
    });

    it("renders review action buttons on desktop and mobile when onSelectTransaction is provided", () => {
        const onSelect = vi.fn();
        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onSelectTransaction={onSelect}
            />
        );

        expect(screen.getByText("Action")).toBeInTheDocument();
        const desktopReviewBtn = screen.getByRole("button", { name: "Review" });
        fireEvent.click(desktopReviewBtn);
        expect(onSelect).toHaveBeenCalledWith(sample[0]);

        const mobileReviewBtn = screen.getByRole("button", { name: "Review / Fix" });
        fireEvent.click(mobileReviewBtn);
        expect(onSelect).toHaveBeenCalledTimes(2);
    });

    // AC-reconciliation.2465.2
    it("AC-reconciliation.2465.2 defaults transaction status to matched when the statement is approved", () => {
        const { status: _omittedStatus, ...withoutStatus } = sample[0];
        void _omittedStatus;
        render(<TransactionTable transactions={[withoutStatus as BankStatementTransaction]} currency="SGD" statementStatus="approved" />);
        expect(screen.getAllByText("matched").length).toBeGreaterThan(0);
        expect(screen.queryByText("pending")).not.toBeInTheDocument();
    });

    it("shows an explicit transaction status and defaults to pending for an unapproved statement", () => {
        const { status: _omittedStatus, ...withoutStatus } = sample[0];
        void _omittedStatus;
        render(<TransactionTable transactions={[{ ...sample[0], id: "t-unmatched", status: "unmatched" }, { ...withoutStatus, id: "t-default" } as BankStatementTransaction]} currency="SGD" statementStatus="parsed" />);
        expect(screen.getByText("unmatched")).toBeInTheDocument();
        expect(screen.getByText("pending")).toBeInTheDocument();
        expect(screen.queryByText("matched")).not.toBeInTheDocument();
    });

    // AC-extraction.fe-stage1-review.21
    it("AC-extraction.fe-stage1-review.21 shows the status under the description, not in a column, and only with a statement status", () => {
        const { rerender } = render(<TransactionTable transactions={sample} currency="SGD" />);
        expect(screen.queryByText("pending")).not.toBeInTheDocument();
        rerender(<TransactionTable transactions={sample} currency="SGD" statementStatus="parsed" />);
        expect(screen.queryByRole("columnheader", { name: "Status" })).not.toBeInTheDocument();
        const region = screen.getByTestId("stage1-desktop-transaction-region");
        const descriptionCell = within(region).getByTitle("Coffee").closest("td");
        expect(descriptionCell).not.toBeNull();
        expect(within(descriptionCell as HTMLElement).getByText("pending")).toBeInTheDocument();
    });
});
