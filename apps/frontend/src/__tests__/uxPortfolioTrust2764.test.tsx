import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortfolioPage from "@/app/(main)/portfolio/page";
import {
  InvestmentPerformanceSchedule,
  formatPerformanceSourceLink,
} from "@/components/portfolio/InvestmentPerformanceSchedule";
import {
  AllocationChart,
  formatAllocationCategory,
} from "@/components/portfolio/PortfolioSummary";
import { apiOperation } from "@/lib/api-client";

const navState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navState.replace, push: vi.fn() }),
  useSearchParams: () => navState.searchParams,
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  TestWrapper.displayName = "UxPortfolioTrust2764Wrapper";
  return TestWrapper;
}

describe("Issue #2764 portfolio valuation provenance, donut legends, and net-worth bars", () => {
  const mockedApiOperation = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApiOperation.mockReset();
    navState.searchParams = new URLSearchParams();
  });

  it("humanizes raw price_source UUID links, statement UUIDs, provider names, and report_section", () => {
    expect(
      formatPerformanceSourceLink(
        "price_source:override:AAPL:1581301e-269d-4847-8fb7-fd21763d1f0d:2025-03-31",
      ),
    ).toBe("Manual price · AAPL (2025-03-31)");
    expect(
      formatPerformanceSourceLink(
        "price_source:stock_price:NVDA:5ec4d3e2-256c-4c11-8de1-40f74d1802c1:2026-10-26",
      ),
    ).toBe("Market price · NVDA (2026-10-26)");
    expect(
      formatPerformanceSourceLink(
        "price_source:atomic_position:STI.SI:e8b2bbe5-85bc-4796-9d10-450c1b400ead:2025-03-31",
      ),
    ).toBe("Position snapshot · STI.SI (2025-03-31)");
    expect(
      formatPerformanceSourceLink(
        "statement:9f38b1a2-1111-4222-8333-444455556666",
      ),
    ).toBe("Statement record");
    expect(
      formatPerformanceSourceLink("report_section:investment_performance"),
    ).toBe("Report section · Investment Performance");

    const { container } = render(
      <InvestmentPerformanceSchedule
        schedule={
          {
            period_start: "2025-01-01",
            period_end: "2025-12-31",
            as_of_date: "2025-12-31",
            currency: "SGD",
            xirr: "10.00",
            time_weighted_return: "8.00",
            money_weighted_return: "9.50",
            dividend_yield: "2.10",
            realized_pnl: "100.00",
            unrealized_pnl: "250.00",
            dividend_income: "45.00",
            holdings: [
              {
                asset_identifier: "AAPL",
                quantity: "10",
                cost_basis: "1000.00",
                market_value: "1250.00",
                unrealized_pnl: "250.00",
                realized_pnl: "100.00",
                dividend_income: "45.00",
                currency: "SGD",
              },
            ],
            allocation: [],
            data_freshness: {
              latest_price_date: "2025-03-31",
              market_data_provider: "Interactive Brokers, yahoo_finance",
              stale: false,
              stale_holdings: [],
              manual_override_basis: "NVDA:2025-03-31",
            },
            source_links: [
              "price_source:override:AAPL:1581301e-269d-4847-8fb7-fd21763d1f0d:2025-03-31",
              "price_source:stock_price:NVDA:5ec4d3e2-256c-4c11-8de1-40f74d1802c1:2026-10-26",
              "statement:9f38b1a2-1111-4222-8333-444455556666",
              "report_section:investment_performance",
            ],
            notes: [],
          } as never
        }
      />,
    );

    expect(screen.getByText("Investment Performance")).toBeInTheDocument();
    expect(
      screen.getByText("Provider: Interactive Brokers, Yahoo Finance"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Manual override: NVDA (2025-03-31)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Manual price · AAPL (2025-03-31)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Market price · NVDA (2026-10-26)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Statement record")).toBeInTheDocument();
    expect(
      screen.getByText("Report section · Investment Performance"),
    ).toBeInTheDocument();

    const text = container.textContent ?? "";
    expect(text).not.toContain("price_source:");
    expect(text).not.toContain("yahoo_finance");
    expect(text).not.toMatch(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i,
    );
  });

  it("renders a single donut legend without duplicate '48% · 48' shares and normalizes Unknown categories", async () => {
    expect(formatAllocationCategory("Unknown", "sector")).toBe(
      "Unclassified sector",
    );
    expect(formatAllocationCategory("", "geography")).toBe(
      "Unclassified geography",
    );

    mockedApiOperation.mockResolvedValue([
      { category: "Technology", value: "4810.00", percentage: "48.1", count: 1 },
      { category: "Unknown", value: "5190.00", percentage: "51.9", count: 2 },
    ]);

    const { container } = render(
      <AllocationChart type="sector" title="Sector Allocation" />,
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(
        screen.getAllByText("Unclassified sector").length,
      ).toBeGreaterThanOrEqual(1),
    );
    expect(screen.getByText("48.1%")).toBeInTheDocument();
    expect(screen.getByText("51.9%")).toBeInTheDocument();
    expect(
      screen.queryByTestId("pie-segment-share-Technology"),
    ).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("48% · 48");
    expect(container.textContent).not.toContain("Unknown");
  });

  it("truncates long manual valuation links (#2762) and clarifies negative/leveraged net-worth allocation bars", async () => {
    mockedApiOperation.mockImplementation(async (operationId: string) => {
      if (operationId === "get_holdings_portfolio_holdings_get") {
        return {
          items: [
            {
              id: "h1",
              user_id: "u1",
              account_id: "acc1",
              asset_identifier: "AAPL",
              quantity: "10",
              cost_basis: "1500.00",
              market_value: "1800.00",
              unrealized_pnl: "300.00",
              unrealized_pnl_percent: "20.00",
              currency: "SGD",
              native_cost_basis: "1500.00",
              native_currency: "SGD",
              reporting_cost_basis: "1500.00",
              reporting_currency: "SGD",
              acquisition_date: "2025-01-15",
              status: "active",
              account_name: "IBKR",
              asset_type: "Equity",
              sector: "Technology",
              geography: "US",
            },
          ],
          total: 1,
          warnings: [],
        };
      }
      if (operationId === "get_portfolio_summary_portfolio_summary_get") {
        return {
          total_market_value: "1800.00",
          total_cost_basis: "1500.00",
          total_unrealized_pnl: "300.00",
          total_unrealized_pnl_percent: "20.00",
          total_realized_pnl: "0.00",
          total_realized_pnl_percent: "0.00",
          net_pnl: "300.00",
          net_pnl_percent: "20.00",
          holdings_count: 1,
          active_positions_count: 1,
          disposed_positions_count: 0,
          currency: "SGD",
          realized_pnl_ytd: "0.00",
          dividend_income_ytd: "200.00",
        };
      }
      if (
        operationId ===
        "get_investment_performance_report_schedule_portfolio_performance_report_schedule_get"
      ) {
        return {
          period_start: "2025-01-01",
          period_end: "2025-12-31",
          as_of_date: "2025-12-31",
          currency: "SGD",
          xirr: null,
          time_weighted_return: null,
          money_weighted_return: null,
          realized_pnl: "0.00",
          unrealized_pnl: "300.00",
          dividend_income: "200.00",
          dividend_yield: null,
          holdings: [],
          allocation: [],
          data_freshness: {
            latest_price_date: "2025-12-31",
            market_data_provider: "Manual",
            stale: false,
            stale_holdings: [],
            manual_override_basis: null,
          },
          source_links: [],
          notes: [],
        };
      }
      if (
        operationId === "net_worth_allocation_reports_net_worth_allocation_get"
      ) {
        return {
          as_of_date: "2025-12-31",
          currency: "SGD",
          include_restricted: true,
          total_assets: "1121190.40",
          total_liabilities: "647900.00",
          net_worth: "473290.40",
          excluded_holdings: [],
          rows: [
            {
              asset_class: "real_estate",
              liquidity_class: "illiquid",
              source_currency: "SGD",
              value: "1050000.00",
              percentage_of_net_worth: "221.9",
              source_line_count: 1,
              source_lines: [
                {
                  source_type: "manual_valuation",
                  source_id: "val-prop-1",
                  label:
                    "HDB Valuation Report 2025-Q1 Long Identifier Without Spaces",
                  value: "1050000.00",
                },
              ],
            },
            {
              asset_class: "liability",
              liquidity_class: "liability",
              source_currency: "SGD",
              value: "-647900.00",
              percentage_of_net_worth: "-136.9",
              source_line_count: 1,
              source_lines: [
                {
                  source_type: "manual_valuation",
                  source_id: "val-loan-1",
                  label: "Mortgage Statement 2025-Q1",
                  value: "-647900.00",
                },
              ],
            },
          ],
        };
      }
      return [];
    });

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });

    const manualLink = await within(panel).findByRole("link", {
      name: "HDB Valuation Report 2025-Q1 Long Identifier Without Spaces",
    });
    expect(manualLink).toHaveClass("block", "truncate");

    expect(
      within(panel).getByText("Gross share of net worth"),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("Liability offset of net worth"),
    ).toBeInTheDocument();

    const assetBar = within(panel).getByTestId("allocation-bar-asset");
    const liabilityBar = within(panel).getByTestId("allocation-bar-liability");
    expect(assetBar).toHaveStyle({ width: "93.7%" });
    expect(liabilityBar).toHaveClass("bg-[var(--error)]/60");
    expect(liabilityBar).toHaveStyle({ width: "100.0%" });
  });
});
