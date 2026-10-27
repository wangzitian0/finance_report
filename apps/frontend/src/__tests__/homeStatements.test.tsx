import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";

import { StatementCockpit } from "@/components/reports/StatementCockpit";
import { readReportFilters } from "@/hooks/useReportFilters";
import { apiOperation } from "@/lib/api-client";

vi.mock("next/link", () => ({
    default: ({ href, children, ...props }: { href: string; children: ReactNode; [key: string]: unknown }) => (
        <a href={href} {...props}>{children}</a>
    ),
}));

vi.mock("@/lib/api-client", () => ({
    apiOperation: vi.fn(),
}));

const balanceSheetAt = (asOfDate: string, totalAssets: string, totalLiabilities: string) => ({
    as_of_date: asOfDate,
    currency: "SGD",
    assets: [
        { account_id: "acc-cash", name: "DBS Multiplier", type: "ASSET", amount: "12000" },
        { account_id: "acc-broker", name: "IBKR Portfolio", type: "ASSET", amount: "28000" },
        { account_id: "acc-empty", name: "Closed Account", type: "ASSET", amount: "0" },
    ],
    liabilities: [{ account_id: "acc-card", name: "Visa Infinite", type: "LIABILITY", amount: "2000" }],
    equity: [],
    total_assets: totalAssets,
    total_liabilities: totalLiabilities,
    total_equity: "38000",
    equation_delta: "0",
    is_balanced: true,
    opening_balance_warnings: [{ type: "missing_opening_balance", message: "Record opening balances to trust this total." }],
});

const incomeStatement = {
    start_date: "2026-01-01",
    end_date: "2026-03-31",
    currency: "SGD",
    income: [{ account_id: "acc-salary", name: "Base Salary", type: "INCOME", amount: "9000" }],
    expenses: [{ account_id: "acc-rent", name: "Apartment Rent", type: "EXPENSE", amount: "4500" }],
    total_income: "9000",
    total_expenses: "4500",
    net_income: "4500",
    trends: [],
};

const cashFlow = {
    start_date: "2026-01-01",
    end_date: "2026-03-31",
    currency: "SGD",
    operating: [{ line_id: "op-1", category: "operating", subcategory: "Salary received", amount: "9000", account_id: "acc-cash", event_count: 3 }],
    investing: [{ line_id: "inv-1", category: "investing", subcategory: "Broker transfer", amount: "-3000", account_id: null, event_count: 1 }],
    financing: [{ line_id: "fin-1", category: "financing", subcategory: "Card repayment", description: "Outflow - DBS Multiplier", amount: "-500", account_id: "acc-cash", event_count: 1 }],
    summary: {
        operating_activities: "4500",
        investing_activities: "-3000",
        financing_activities: "0",
        net_cash_flow: "1500",
        beginning_cash: "10000",
        ending_cash: "11500",
    },
};

const Q1_2026 = readReportFilters(new URLSearchParams("period=1Q&end=2026-03-31"), new Date(2026, 9, 22));

describe("Three-statement cockpit (#2621 LC, #2548 P1)", () => {
    const mockedApiOperation = vi.mocked(apiOperation);

    beforeEach(() => {
        mockedApiOperation.mockReset();
        mockedApiOperation.mockImplementation(((operationId: string, request: { query?: Record<string, unknown> }) => {
            if (operationId === "balance_sheet_reports_balance_sheet_get") {
                return Promise.resolve(
                    request.query?.as_of_date === "2025-12-31"
                        ? balanceSheetAt("2025-12-31", "32000", "2000")
                        : balanceSheetAt("2026-03-31", "40000", "2000"),
                );
            }
            if (operationId === "income_statement_reports_income_statement_get") return Promise.resolve(incomeStatement);
            if (operationId === "cash_flow_reports_cash_flow_get") return Promise.resolve(cashFlow);
            if (operationId === "account_lineage_reports_account_lineage_get") return new Promise(() => undefined);
            return Promise.reject(new Error(`unexpected ${operationId}`));
        }) as never);
    });

    // AC-reporting.fe-ia-reports.26
    it("deep-links each of the three statements to its report tab and keeps the period", () => {
        render(<StatementCockpit filters={Q1_2026} />);

        expect(screen.getByRole("region", { name: "Three-statement cockpit" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Open the balance sheet report" })).toHaveAttribute("href", "/reports?period=1Q&end=2026-03-31&tab=balance-sheet");
        expect(screen.getByRole("link", { name: "Open the income statement report" })).toHaveAttribute("href", "/reports?period=1Q&end=2026-03-31&tab=income-statement");
        expect(screen.getByRole("link", { name: "Open the cash flow report" })).toHaveAttribute("href", "/reports?period=1Q&end=2026-03-31&tab=cash-flow");
    });

    // AC-reporting.fe-period-cockpit.4
    // AC-reporting.2548.1
    it("AC-reporting.fe-period-cockpit.4 shows the live metrics of the period on each statement card", async () => {
        render(<StatementCockpit filters={Q1_2026} />);

        const balance = screen.getByTestId("cockpit-card-balance-sheet");
        await waitFor(() => expect(within(balance).getByText("Net worth").nextElementSibling).toHaveTextContent("SGD 38,000"));
        // Net worth 38,000 at 2026-03-31 minus 30,000 at the opening date 2025-12-31.
        expect(within(balance).getByText("Change in period").nextElementSibling).toHaveTextContent("+SGD 8,000");
        expect(within(balance).getByText("Total assets").nextElementSibling).toHaveTextContent("SGD 40,000");
        expect(within(balance).getByText("Total liabilities").nextElementSibling).toHaveTextContent("SGD 2,000");

        const income = screen.getByTestId("cockpit-card-income-statement");
        await waitFor(() => expect(within(income).getByText("Income").nextElementSibling).toHaveTextContent("SGD 9,000"));
        expect(within(income).getByText("Expenses").nextElementSibling).toHaveTextContent("SGD 4,500");
        expect(within(income).getByText("Net income").nextElementSibling).toHaveTextContent("+SGD 4,500");
        expect(within(income).getByText("Savings rate").nextElementSibling).toHaveTextContent("50%");

        const cash = screen.getByTestId("cockpit-card-cash-flow");
        await waitFor(() => expect(within(cash).getByText("Operating").nextElementSibling).toHaveTextContent("+SGD 4,500"));
        expect(within(cash).getByText("Investing").nextElementSibling).toHaveTextContent("-SGD 3,000");
        expect(within(cash).getByText("Financing").nextElementSibling).toHaveTextContent("SGD 0");
        expect(within(cash).getByText("Net change").nextElementSibling).toHaveTextContent("+SGD 1,500");

        const queries = (operationId: string) =>
            mockedApiOperation.mock.calls.filter(([id]) => id === operationId).map(([, request]) => (request as { query: Record<string, unknown> }).query);
        expect(queries("balance_sheet_reports_balance_sheet_get").map((q) => q.as_of_date).sort()).toEqual(["2025-12-31", "2026-03-31"]);
        expect(queries("income_statement_reports_income_statement_get")).toEqual([expect.objectContaining({ start_date: "2026-01-01", end_date: "2026-03-31" })]);
        expect(queries("cash_flow_reports_cash_flow_get")).toEqual([expect.objectContaining({ start_date: "2026-01-01", end_date: "2026-03-31" })]);
        expect(screen.getByText("Opening balances not recorded")).toBeInTheDocument();
    });

    // AC-reporting.fe-period-cockpit.4
    it("AC-reporting.fe-period-cockpit.4 reloads all three cards for a new period and reads no opening balance sheet for All", async () => {
        const { rerender } = render(<StatementCockpit filters={Q1_2026} />);
        await waitFor(() => expect(screen.getByText("Change in period").nextElementSibling).toHaveTextContent("+SGD 8,000"));
        mockedApiOperation.mockClear();

        rerender(<StatementCockpit filters={readReportFilters(new URLSearchParams("period=All&end=2026-03-31"), new Date(2026, 9, 22))} />);
        // A card never shows the numbers of the previous period under the new period.
        expect(within(screen.getByTestId("cockpit-card-income-statement")).getByRole("status")).toHaveTextContent("Loading…");
        expect(within(screen.getByTestId("cockpit-card-cash-flow")).getByRole("status")).toHaveTextContent("Loading…");
        await waitFor(() =>
            expect(mockedApiOperation).toHaveBeenCalledWith(
                "income_statement_reports_income_statement_get",
                expect.objectContaining({ query: expect.objectContaining({ start_date: "2000-01-01", end_date: "2026-03-31" }) }),
            ),
        );
        expect(mockedApiOperation).toHaveBeenCalledWith(
            "cash_flow_reports_cash_flow_get",
            expect.objectContaining({ query: expect.objectContaining({ start_date: "2000-01-01" }) }),
        );
        await waitFor(() => expect(screen.getByText("Change in period").nextElementSibling).toHaveTextContent("—"));
        // The balance sheet at the period end comes from the cache, and `All` has no opening balance sheet.
        expect(mockedApiOperation.mock.calls.filter(([id]) => id === "balance_sheet_reports_balance_sheet_get")).toEqual([]);
    });

    // AC-reporting.fe-period-cockpit.5
    // AC-reporting.2548.2
    it("AC-reporting.fe-period-cockpit.5 switches the statement with the segmented control and drills a row into its source transactions", async () => {
        render(<StatementCockpit filters={Q1_2026} />);

        const switcher = await screen.findByRole("tablist", { name: "Statement switcher" });
        expect(within(switcher).getByRole("tab", { name: "Balance" })).toHaveAttribute("aria-selected", "true");
        // On a phone only the selected card shows.
        expect(screen.getByTestId("cockpit-card-balance-sheet")).not.toHaveClass("hidden");
        expect(screen.getByTestId("cockpit-card-income-statement")).toHaveClass("hidden", "sm:block");

        const rows = await screen.findAllByRole("button", { name: /View source transactions for/ });
        // The largest lines first. A zero line has no row.
        expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
            "View source transactions for IBKR Portfolio",
            "View source transactions for DBS Multiplier",
            "View source transactions for Visa Infinite",
        ]);
        fireEvent.click(rows[0]);
        await waitFor(() =>
            expect(mockedApiOperation).toHaveBeenCalledWith("account_lineage_reports_account_lineage_get", {
                query: { account_id: "acc-broker", as_of_date: "2026-03-31", currency: "SGD", start_date: undefined },
            }),
        );
        fireEvent.click(screen.getByRole("button", { name: "Close panel" }));

        fireEvent.click(within(switcher).getByRole("tab", { name: "Income" }));
        expect(screen.getByTestId("cockpit-card-income-statement")).not.toHaveClass("hidden");
        expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveClass("hidden");
        fireEvent.click(await screen.findByRole("button", { name: "View source transactions for Base Salary" }));
        await waitFor(() =>
            expect(mockedApiOperation).toHaveBeenCalledWith("account_lineage_reports_account_lineage_get", {
                query: { account_id: "acc-salary", as_of_date: "2026-03-31", currency: "SGD", start_date: "2026-01-01" },
            }),
        );
        fireEvent.click(screen.getByRole("button", { name: "Close panel" }));

        fireEvent.click(within(switcher).getByRole("tab", { name: "Cash" }));
        // A cash-flow line without an account has no source drill-down. Two lines of one account
        // (an inflow and an outflow) are two rows, named by their description.
        expect(await screen.findByRole("button", { name: "View source transactions for Salary received" })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "View source transactions for Outflow - DBS Multiplier" }));
        await waitFor(() =>
            expect(mockedApiOperation).toHaveBeenCalledWith("account_lineage_reports_account_lineage_get", {
                query: { account_id: "acc-cash", as_of_date: "2026-03-31", currency: "SGD", start_date: "2026-01-01" },
            }),
        );
        expect(screen.queryByRole("button", { name: "View source transactions for Broker transfer" })).toBeNull();
    });

    // AC-reporting.fe-period-cockpit.5
    it("omits the no-op Statement switcher when all three statements have zero drill-down rows (#2730)", async () => {
        mockedApiOperation.mockImplementation(((operationId: string) => {
            if (operationId === "balance_sheet_reports_balance_sheet_get") {
                return Promise.resolve({
                    ...balanceSheetAt("2026-03-31", "0", "0"),
                    assets: [],
                    liabilities: [],
                });
            }
            if (operationId === "income_statement_reports_income_statement_get") {
                return Promise.resolve({
                    ...incomeStatement,
                    income: [],
                    expenses: [],
                    total_income: "0",
                    total_expenses: "0",
                    net_income: "0",
                });
            }
            if (operationId === "cash_flow_reports_cash_flow_get") {
                return Promise.resolve({
                    ...cashFlow,
                    operating: [],
                    investing: [],
                    financing: [],
                });
            }
            return Promise.reject(new Error(`unexpected ${operationId}`));
        }) as never);

        render(<StatementCockpit filters={Q1_2026} />);
        await waitFor(() =>
            expect(within(screen.getByTestId("cockpit-card-balance-sheet")).getByText("Total assets").nextElementSibling).toHaveTextContent("SGD 0"),
        );
        expect(screen.queryByRole("tablist", { name: "Statement switcher" })).toBeNull();
        expect(screen.getByTestId("cockpit-card-balance-sheet")).not.toHaveClass("hidden");
        expect(screen.getByTestId("cockpit-card-income-statement")).not.toHaveClass("hidden");
        expect(screen.getByTestId("cockpit-card-cash-flow")).not.toHaveClass("hidden");
    });

    it("shows a retry when a statement fails and a loading line while a card waits", async () => {
        let failIncome = true;
        mockedApiOperation.mockImplementation(((operationId: string) => {
            if (operationId === "income_statement_reports_income_statement_get") {
                return failIncome ? Promise.reject(new Error("income down")) : Promise.resolve(incomeStatement);
            }
            if (operationId === "cash_flow_reports_cash_flow_get") return new Promise(() => undefined);
            return Promise.resolve(balanceSheetAt("2026-03-31", "40000", "2000"));
        }) as never);
        render(<StatementCockpit filters={Q1_2026} />);

        expect((await screen.findByText("Statements unavailable: income down")).closest("[role='alert']")).not.toBeNull();
        expect(within(screen.getByTestId("cockpit-card-cash-flow")).getByRole("status")).toHaveTextContent("Loading…");
        expect(within(screen.getByTestId("cockpit-card-income-statement")).getByText("No data for this period.")).toBeInTheDocument();

        failIncome = false;
        fireEvent.click(screen.getByRole("button", { name: "Retry" }));
        await waitFor(() => expect(screen.queryByText(/Statements unavailable/)).toBeNull());
        expect(within(screen.getByTestId("cockpit-card-income-statement")).getByText("Savings rate").nextElementSibling).toHaveTextContent("50%");
    });
});
