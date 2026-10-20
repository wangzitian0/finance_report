import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ThreeStatementNav, resolvePeriodRange } from "@/components/home/ThreeStatementNav";
import { apiOperation } from "@/lib/api-client";
import type { BalanceSheetResponse, IncomeStatementResponse } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
    apiOperation: vi.fn(),
}));

const sampleBalanceSheet: BalanceSheetResponse = {
    as_of_date: "2026-03-31",
    currency: "SGD",
    assets: [
        { account_id: "acc-cash", name: "DBS Multiplier", type: "ASSET", amount: "12000" },
        { account_id: "acc-broker", name: "IBKR Portfolio", type: "ASSET", amount: "28000" },
    ],
    liabilities: [
        { account_id: "acc-card", name: "Visa Infinite", type: "LIABILITY", amount: "2000" },
    ],
    equity: [],
    total_assets: "40000",
    total_liabilities: "2000",
    total_equity: "38000",
    net_income: "4500",
    net_worth_adjustment_gain_loss: "0",
    unrealized_fx_gain_loss: "0",
    equation_delta: "0",
    cta_adjustment: "0",
    is_balanced: true,
};

const sampleIncomeStatement: IncomeStatementResponse = {
    start_date: "2026-01-01",
    end_date: "2026-03-31",
    currency: "SGD",
    income: [
        { account_id: "acc-salary", name: "Base Salary", type: "INCOME", amount: "9000" },
    ],
    expenses: [
        { account_id: "acc-rent", name: "Apartment Rent", type: "EXPENSE", amount: "4500" },
    ],
    total_income: "9000",
    total_expenses: "4500",
    net_income: "4500",
    trends: [
        { period_start: "2026-01-01", period_end: "2026-01-31", total_income: "3000", total_expenses: "1500", net_income: "1500" },
        { period_start: "2026-02-01", period_end: "2026-02-28", total_income: "3000", total_expenses: "1500", net_income: "1500" },
        { period_start: "2026-03-01", period_end: "2026-03-31", total_income: "3000", total_expenses: "1500", net_income: "1500" },
    ],
};

describe("Home three-statement entry (EPIC-022 AC22.21.6 & #2548)", () => {
    const mockedApiOperation = vi.mocked(apiOperation);

    beforeEach(() => {
        mockedApiOperation.mockReset();
    });

    // AC-reporting.fe-ia-reports.26
    it("deep-links each of the three statements to its full report", () => {
        render(<ThreeStatementNav />);

        expect(screen.getByRole("navigation", { name: "Financial statements" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Balance Sheet/ })).toHaveAttribute(
            "href",
            "/reports/balance-sheet",
        );
        expect(screen.getByRole("link", { name: /Income/ })).toHaveAttribute(
            "href",
            "/reports/income-statement",
        );
        expect(screen.getByRole("link", { name: /Cash Flow/ })).toHaveAttribute(
            "href",
            "/reports/cash-flow",
        );
    });

    // AC-reporting.2548.1
    it("AC-reporting.2548.1 switches reporting period preset and updates three-statement cockpit metrics", () => {
        const onPeriodPresetChange = vi.fn();
        const onIncludeRestrictedChange = vi.fn();
        render(
            <ThreeStatementNav
                balanceSheet={sampleBalanceSheet}
                incomeStatement={sampleIncomeStatement}
                periodPreset="1Q"
                onPeriodPresetChange={onPeriodPresetChange}
                includeRestricted={false}
                onIncludeRestrictedChange={onIncludeRestrictedChange}
            />,
        );

        const scopeToggle = screen.getByRole("button", { name: "Toggle restricted holdings scope" });
        expect(scopeToggle).toHaveAttribute("aria-pressed", "false");
        expect(scopeToggle).toHaveTextContent("Scope: Liquid");
        fireEvent.click(scopeToggle);
        expect(onIncludeRestrictedChange).toHaveBeenCalledWith(true);

        const periodGroup = screen.getByRole("group", { name: "Reporting period" });
        expect(periodGroup).toBeInTheDocument();
        for (const preset of ["1M", "1Q", "1Y", "YTD", "3Y", "All"]) {
            expect(screen.getByRole("button", { name: `Period ${preset}` })).toBeInTheDocument();
        }
        expect(screen.getByRole("button", { name: "Period 1Q" })).toHaveAttribute("aria-pressed", "true");

        expect(screen.getByTestId("cockpit-card-balance-sheet")).toHaveTextContent(/38,000/);
        expect(screen.getByTestId("cockpit-card-income-statement")).toHaveTextContent(/4,500/);
        expect(screen.getByTestId("cockpit-card-income-statement")).toHaveTextContent(/50%/);
        expect(screen.getByTestId("cockpit-card-cash-flow")).toHaveTextContent(/12,000/);

        fireEvent.click(screen.getByRole("button", { name: "Period 3Y" }));
        expect(onPeriodPresetChange).toHaveBeenCalledWith("3Y");

        const range1M = resolvePeriodRange("1M", new Date(2026, 2, 15));
        const range1Q = resolvePeriodRange("1Q", new Date(2026, 2, 15));
        const range1Y = resolvePeriodRange("1Y", new Date(2026, 2, 15));
        const rangeYTD = resolvePeriodRange("YTD", new Date(2026, 2, 15));
        const range3Y = resolvePeriodRange("3Y", new Date(2026, 2, 15));
        const rangeAll = resolvePeriodRange("All", new Date(2026, 2, 15));
        expect(range1M.startDate).toBe("2026-03-01");
        expect(range1M.endDate).toBe("2026-03-15");
        expect(range1Q.startDate).toBe("2026-01-01");
        expect(range1Y.startDate).toBe("2025-04-01");
        expect(rangeYTD.startDate).toBe("2026-01-01");
        expect(range3Y.startDate).toBe("2023-04-01");
        expect(rangeAll.startDate).toBe("2000-01-01");
    });

    // AC-reporting.2548.2
    it("AC-reporting.2548.2 switches active statement breakdown and opens AccountLineageDrawer on account click", async () => {
        mockedApiOperation.mockResolvedValue({
            account_id: "acc-salary",
            account_name: "Base Salary",
            as_of_date: "2026-03-31",
            currency: "SGD",
            balance: "9000",
            lines: [],
        } as never);

        render(
            <ThreeStatementNav
                balanceSheet={sampleBalanceSheet}
                incomeStatement={sampleIncomeStatement}
                periodPreset="1Q"
            />,
        );

        fireEvent.click(screen.getByRole("button", { name: "Period YTD" }));
        expect(screen.getByRole("button", { name: "Period YTD" })).toHaveAttribute("aria-pressed", "true");

        const switcher = screen.getByRole("tablist", { name: "Statement breakdown switcher" });
        expect(switcher).toBeInTheDocument();

        const visualChart = screen.getByTestId("cockpit-visual-chart");
        expect(visualChart).toHaveAttribute("aria-label", "Cockpit balance visual chart");
        expect(visualChart).toHaveTextContent(/Assets vs Liabilities/i);

        expect(screen.getByRole("button", { name: /Drill down DBS Multiplier/i })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("tab", { name: "Cash Breakdown" }));
        expect(screen.getByTestId("cockpit-visual-chart")).toHaveAttribute("aria-label", "Cockpit cash visual chart");
        expect(screen.getByTestId("cockpit-visual-chart")).toHaveTextContent(/Liquid Cash vs Total Assets/i);
        expect(screen.getByRole("button", { name: /Drill down DBS Multiplier/i })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("tab", { name: "Income Breakdown" }));
        expect(screen.getByTestId("cockpit-visual-chart")).toHaveAttribute("aria-label", "Cockpit income visual chart");
        expect(screen.getByTestId("cockpit-visual-chart")).toHaveTextContent(/Income vs Expenses/i);
        const salaryButton = screen.getByRole("button", { name: /Drill down Base Salary/i });
        expect(salaryButton).toBeInTheDocument();

        fireEvent.click(salaryButton);

        await waitFor(() =>
            expect(mockedApiOperation).toHaveBeenCalledWith(
                "account_lineage_reports_account_lineage_get",
                expect.objectContaining({
                    query: expect.objectContaining({
                        account_id: "acc-salary",
                        currency: "SGD",
                    }),
                }),
            ),
        );
        expect(await screen.findByText(/Sources · Base Salary/)).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
        expect(screen.queryByText(/Sources · Base Salary/)).toBeNull();
    });
});
