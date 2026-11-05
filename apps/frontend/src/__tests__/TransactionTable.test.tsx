import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import * as money from "@/lib/audit/money";
import { TransactionTable } from "@/components/review/StatementReview";
import { normalizeBankStatement, toTransactionViewModel, type BankStatementTransaction } from "@/lib/types";
import type { Schemas } from "@/lib/api-schema";

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

    // AC-extraction.fe-stage1-review.23
    it("AC-extraction.fe-stage1-review.23 pins the low-confidence rows on top and keeps the other rows in statement order", () => {
        const row = (id: string, description: string, tier: BankStatementTransaction["confidence_tier"]): BankStatementTransaction => ({
            ...sample[0],
            id,
            description,
            confidence_tier: tier,
        });
        // The October statement of #2647: six rows where the LOW rows are rows 4 and 6.
        const rows = [
            row("t-salary", "Salary", "HIGH"),
            row("t-grab", "Grab ride", "MEDIUM"),
            row("t-rent", "Rent", "TRUSTED"),
            row("t-fee", "Card fee", "LOW"),
            row("t-groceries", "Groceries", "HIGH"),
            row("t-paynow", "PayNow Transfer REF 4471", "LOW"),
        ];
        render(<TransactionTable transactions={rows} currency="SGD" />);

        // Only the LOW rows move. MEDIUM, HIGH and TRUSTED rows keep the statement order: no sort by tier.
        const expected = ["Card fee", "PayNow Transfer REF 4471", "Salary", "Grab ride", "Rent", "Groceries"];
        const region = screen.getByTestId("stage1-desktop-transaction-region");
        const desktopRows = within(region).getAllByRole("row").slice(1);
        expect(desktopRows.map((tr) => tr.querySelector("[title]")?.getAttribute("title"))).toEqual(expected);
        // A pinned row states its position in statement order; the other rows sit at that position.
        expect(desktopRows.map((tr) => tr.querySelector("[data-testid='date-row-number']")?.textContent ?? null)).toEqual([
            "Row 4 of 6", "Row 6 of 6", null, null, null, null,
        ]);
        expect(screen.getByText("6 total · in statement order")).toBeInTheDocument();
        const mobileCards = within(screen.getByTestId("stage1-mobile-transaction-list")).getAllByRole("article");
        expect(mobileCards.map((card) => card.getAttribute("data-testid")?.replace("stage1-mobile-transaction-card-", ""))).toEqual([
            "t-fee", "t-paynow", "t-salary", "t-grab", "t-rent", "t-groceries",
        ]);
        expect(within(mobileCards[1]).getByTestId("date-row-number")).toHaveTextContent("Row 6 of 6");
        expect(within(mobileCards[2]).queryByTestId("date-row-number")).toBeNull();
        expect(screen.getByTestId("low-confidence-count")).toHaveTextContent("2 low confidence · shown first");
    });

    // AC-extraction.fe-stage1-review.23 (#2679)
    it("AC-extraction.fe-stage1-review.23 orders rows by source_row when descending dates and same-day ties differ from date order", () => {
        // Source statement has descending dates (2026-10-25 first, 2026-10-05 last) and a same-day tie on 2026-10-15.
        // Pass the array in ascending date / inverted same-day order to prove the table sorts by source_row, not array or date order.
        const wireRows: Schemas["AtomicTransactionResponse"][] = [
            {
                id: "t-oct05-low",
                statement_id: "s1",
                txn_date: "2026-10-05",
                description: "Oct 5 bottom low row",
                amount: "50.00",
                direction: "OUT",
                reference: null,
                currency: "SGD",
                confidence_tier: "LOW",
                source_row: 4,
                created_at: "2026-10-31T00:01:00Z",
                updated_at: "2026-10-31T00:01:00Z",
            },
            {
                id: "t-oct15-second",
                statement_id: "s1",
                txn_date: "2026-10-15",
                description: "Oct 15 second on page",
                amount: "20.00",
                direction: "OUT",
                reference: null,
                currency: "SGD",
                confidence_tier: "HIGH",
                source_row: 3,
                created_at: "2026-10-31T00:02:00Z",
                updated_at: "2026-10-31T00:02:00Z",
            },
            {
                id: "t-oct15-first-low",
                statement_id: "s1",
                txn_date: "2026-10-15",
                description: "Oct 15 first on page (low)",
                amount: "30.00",
                direction: "OUT",
                reference: null,
                currency: "SGD",
                confidence_tier: "LOW",
                source_row: 2,
                created_at: "2026-10-31T00:05:00Z",
                updated_at: "2026-10-31T00:05:00Z",
            },
            {
                id: "t-oct25-top",
                statement_id: "s1",
                txn_date: "2026-10-25",
                description: "Oct 25 top of PDF",
                amount: "100.00",
                direction: "IN",
                reference: null,
                currency: "SGD",
                confidence_tier: "HIGH",
                source_row: 1,
                created_at: "2026-10-31T00:04:00Z",
                updated_at: "2026-10-31T00:04:00Z",
            },
        ];
        const rows = wireRows.map((r) => toTransactionViewModel(r));
        render(<TransactionTable transactions={rows} currency="SGD" />);

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        const desktopRows = within(region).getAllByRole("row").slice(1);
        // Pinned LOW rows follow source_row (Row 2 before Row 4), and unpinned rows follow source_row (Row 1 before Row 3).
        expect(desktopRows.map((tr) => tr.querySelector("[title]")?.getAttribute("title"))).toEqual([
            "Oct 15 first on page (low)",
            "Oct 5 bottom low row",
            "Oct 25 top of PDF",
            "Oct 15 second on page",
        ]);
        expect(desktopRows.map((tr) => tr.querySelector("[data-testid='date-row-number']")?.textContent ?? null)).toEqual([
            "Row 2 of 4",
            "Row 4 of 4",
            null,
            null,
        ]);
        expect(screen.getByText("4 total · in statement order")).toBeInTheDocument();
    });

    // AC-extraction.fe-stage1-review.23
    it("AC-extraction.fe-stage1-review.23 shows no low-confidence count when no row is low", () => {
        render(<TransactionTable transactions={[{ ...sample[0], confidence_tier: "HIGH" }]} currency="SGD" />);
        expect(screen.queryByTestId("low-confidence-count")).toBeNull();
    });

    // AC-extraction.fe-stage1-review.27
    it("AC-extraction.fe-stage1-review.27 shows a row with no confidence tier as not rated, not pinned and not counted", () => {
        // An atomic transaction with no tier, as the API can send it.
        const unrated = toTransactionViewModel({
            id: "t-unrated", statement_id: "s1", txn_date: "2026-10-03", description: "Unrated transfer", amount: "10.00",
            direction: "OUT", reference: null, currency: "SGD", created_at: "", updated_at: "",
        } as Schemas["AtomicTransactionResponse"]);
        expect([unrated.confidence_tier, unrated.confidence]).toEqual([null, undefined]);
        // The unrated row comes before a HIGH row: a sort that moves unrated rows after rated rows fails.
        const rows: BankStatementTransaction[] = [
            unrated as BankStatementTransaction,
            { ...sample[0], id: "t-high", description: "Salary", confidence_tier: "HIGH" },
            { ...sample[0], id: "t-low", description: "Card fee", confidence_tier: "LOW" },
        ];
        render(<TransactionTable transactions={rows} currency="SGD" />);

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        const desktopRows = within(region).getAllByRole("row").slice(1);
        expect(desktopRows.map((tr) => tr.querySelector("[title]")?.getAttribute("title"))).toEqual(["Card fee", "Unrated transfer", "Salary"]);
        expect(within(desktopRows[1]).getByText("Not rated")).toHaveClass("badge-muted");
        expect(within(desktopRows[1]).queryByText(/low/i)).toBeNull();
        expect(within(desktopRows[1]).queryByTestId("date-row-number")).toBeNull();
        expect(screen.getByTestId("low-confidence-count")).toHaveTextContent("1 low confidence · shown first");
    });

    // AC-extraction.fe-stage1-review.24
    it("AC-extraction.fe-stage1-review.24 shows no pending chip on an approved statement read from the API", () => {
        // The API sends no transaction status. Before #2647 the view model filled in "pending".
        const wire = {
            id: "s1", user_id: "u1", file_path: "statements/oct.csv", original_filename: "oct.csv", institution: "DBS",
            status: "approved", account_id: "a1", currency: "SGD", period_start: "2026-10-01", period_end: "2026-10-31",
            opening_balance: "100.00", closing_balance: "120.00", confidence_score: 80, balance_validated: true, validation_error: null,
            created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z",
            transactions: [
                { id: "w1", statement_id: "s1", txn_date: "2026-10-02", description: "Salary", amount: "20.00", direction: "IN", currency: "SGD", confidence_tier: "HIGH", created_at: "", updated_at: "" },
                { id: "w2", statement_id: "s1", txn_date: "2026-10-14", description: "PayNow Transfer REF 4471", amount: "250.00", direction: "OUT", currency: "SGD", confidence_tier: "LOW", created_at: "", updated_at: "" },
            ],
        } as unknown as Schemas["BankStatementResponse"];
        const statement = normalizeBankStatement(wire);

        const { rerender } = render(<TransactionTable transactions={statement.transactions} currency="SGD" statementStatus="approved" />);
        expect(screen.queryByText("pending")).toBeNull();
        expect(screen.getAllByText("matched")).toHaveLength(2);

        // Even if a caller passes status="pending" on an approved statement, it renders matched (#2729).
        rerender(<TransactionTable transactions={statement.transactions.map((t) => ({ ...t, status: "pending" }))} currency="SGD" statementStatus="approved" />);
        expect(screen.queryByText("pending")).toBeNull();
        expect(screen.getAllByText("matched")).toHaveLength(2);

        // The same rows of a parsed statement still wait for review.
        rerender(<TransactionTable transactions={statement.transactions} currency="SGD" statementStatus="parsed" />);
        expect(screen.getAllByText("pending")).toHaveLength(2);
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
