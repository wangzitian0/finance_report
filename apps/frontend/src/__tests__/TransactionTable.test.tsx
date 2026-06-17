import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import * as currency from "@/lib/money";
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

    it("exposes a fixed desktop transaction region for responsive UX proofs", () => {
        render(<TransactionTable transactions={sample} currency="SGD" />);

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        expect(region).toHaveClass("overflow-hidden");
        const table = region.querySelector("table");
        expect(table).toHaveClass("table-fixed", "border-collapse");
        expect(table).toHaveStyle({ width: "calc(100% - 4px)" });
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
        const spy = vi.spyOn(currency, "formatCurrencyLocale");

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
});
