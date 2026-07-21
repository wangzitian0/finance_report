import "@testing-library/jest-dom/vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortfolioPage from "@/app/(main)/portfolio/page";
import { apiFetch } from "@/lib/api";
import type { PortfolioHolding } from "@/lib/types";

const showToastMock = vi.fn();

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("@/components/portfolio/PerformanceCard", () => ({
  PerformanceCard: () => (
    <div data-testid="performance-card">PerformanceCard</div>
  ),
}));

vi.mock("@/components/portfolio/AllocationChart", () => ({
  AllocationChart: ({ type, title }: { type: string; title: string }) => (
    <div data-testid={`allocation-chart-${type}`}>{title}</div>
  ),
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
  TestWrapper.displayName = "PortfolioTestWrapper";
  return TestWrapper;
}

const mockHolding: PortfolioHolding = {
  id: "h1",
  user_id: "u1",
  account_id: "acc1",
  asset_identifier: "AAPL",
  quantity: "10",
  cost_basis: "1500.00",
  market_value: "1800.00",
  unrealized_pnl: "300.00",
  unrealized_pnl_percent: "20.00",
  currency: "USD",
  acquisition_date: "2025-01-15",
  status: "active",
  account_name: "IBKR",
  asset_type: "Equity",
  sector: "Technology",
  geography: "US",
};

const mockHolding2: PortfolioHolding = {
  ...mockHolding,
  id: "h2",
  asset_identifier: "TSLA",
  quantity: "5",
  cost_basis: "1000.00",
  market_value: "900.00",
  unrealized_pnl: "-100.00",
  unrealized_pnl_percent: "-10.00",
  disposal_date: "2025-11-01",
  status: "disposed",
  sector: "Automotive",
};

type NetWorthAllocationMode =
  "default" | "retirement_benefit" | "empty" | "error" | "pending";

function mockPortfolioApi(
  holdings: PortfolioHolding[] = [mockHolding],
  allocationPercentage: string | null = "100.00",
  scheduleCurrency = "USD",
  netWorthAllocationMode: NetWorthAllocationMode = "default",
) {
  const mockedApiFetch = vi.mocked(apiFetch);
  mockedApiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/portfolio/summary")) {
      return Promise.resolve({
        total_market_value: "1800.00",
        total_cost_basis: "1500.00",
        total_unrealized_pnl: "300.00",
        total_unrealized_pnl_percent: "20.00",
        total_realized_pnl: "149.00",
        total_realized_pnl_percent: "9.93",
        net_pnl: "449.00",
        net_pnl_percent: "29.93",
        holdings_count: holdings.length,
        active_positions_count: holdings.filter((h) => h.status === "active")
          .length,
        disposed_positions_count: holdings.filter(
          (h) => h.status === "disposed",
        ).length,
        currency: "SGD",
        realized_pnl_ytd: "149.00",
        dividend_income_ytd: "42.50",
      });
    }
    if (path.startsWith("/api/portfolio/performance/report-schedule")) {
      return Promise.resolve({
        period_start: "2026-01-01",
        period_end: "2026-12-31",
        as_of_date: "2026-12-31",
        currency: scheduleCurrency,
        xirr: "12.50",
        time_weighted_return: "8.30",
        money_weighted_return: "10.10",
        realized_pnl: "149.00",
        unrealized_pnl: "300.00",
        dividend_income: "42.50",
        dividend_yield: "2.36",
        holdings: [
          {
            asset_identifier: "AAPL",
            quantity: "10.000000",
            cost_basis: "1500.00",
            market_value: "1800.00",
            unrealized_pnl: "300.00",
            realized_pnl: "149.00",
            dividend_income: "42.50",
            currency: "SGD",
          },
        ],
        allocation: [
          {
            dimension: "asset_class",
            category: "Public Equity",
            value: "1800.00",
            percentage: allocationPercentage,
            count: 1,
          },
          {
            dimension: "sector",
            category: "Technology",
            value: "1800.00",
            percentage: "100.00",
            count: 1,
          },
        ],
        data_freshness: {
          latest_price_date: "2026-12-31",
          market_data_provider: "Test Broker",
          stale: false,
          stale_holdings: [],
          manual_override_basis: null,
        },
        source_links: ["brokerage_statement:aapl"],
        notes: ["Cost basis uses FIFO where available."],
      });
    }
    if (path.startsWith("/api/reports/net-worth/allocation")) {
      if (netWorthAllocationMode === "pending") {
        return new Promise(() => undefined);
      }
      if (netWorthAllocationMode === "error") {
        return Promise.reject(new Error("allocation unavailable"));
      }
      return Promise.resolve({
        as_of_date: "2026-12-31",
        currency: "SGD",
        include_restricted: !path.includes("include_restricted=false"),
        total_assets: "2100.00",
        total_liabilities: "100.00",
        net_worth: "2000.00",
        rows:
          netWorthAllocationMode === "empty"
            ? []
            : netWorthAllocationMode === "retirement_benefit"
              ? [
                  {
                    asset_class: "retirement_and_benefit_assets",
                    liquidity_class: "restricted",
                    source_currency: "SGD",
                    value: "185000.00",
                    percentage_of_net_worth: "100.00",
                    source_line_count: 1,
                    source_lines: [
                      {
                        source_type: "manual_valuation",
                        source_id: null,
                        label: "401k statement",
                        value: "185000.00",
                        href: "/assets/valuation-components",
                      },
                    ],
                  },
                ]
              : [
                  {
                    asset_class: "public_equity",
                    liquidity_class: "liquid",
                    source_currency: "USD",
                    value: "1800.00",
                    percentage_of_net_worth: allocationPercentage,
                    source_line_count: 2,
                    source_lines: [
                      {
                        source_type: "portfolio_market_adjustment",
                        source_id: null,
                        label: "AAPL market value",
                        value: "1800.00",
                        href: "/portfolio/holdings",
                      },
                      {
                        source_type: "manual_component",
                        source_id: null,
                        label: "Manual adjustment",
                        value: "0.00",
                        href: null,
                      },
                    ],
                  },
                  {
                    asset_class: "cash",
                    liquidity_class: "liquid",
                    source_currency: "SGD",
                    value: "300.00",
                    percentage_of_net_worth: "15.00",
                    source_line_count: 1,
                    source_lines: [
                      {
                        source_type: "ledger_account",
                        source_id: "acc1",
                        label: "Main Bank",
                        value: "300.00",
                        href: "/reports/account-lineage?account_id=acc1&as_of_date=2026-12-31&currency=SGD",
                      },
                    ],
                  },
                  {
                    asset_class: "liability",
                    liquidity_class: "liability",
                    source_currency: "SGD",
                    value: "-100.00",
                    percentage_of_net_worth: "-5.00",
                    source_line_count: 1,
                    source_lines: [
                      {
                        source_type: "ledger_account",
                        source_id: "loan1",
                        label: "Loan",
                        value: "-100.00",
                        href: "/reports/account-lineage?account_id=loan1&as_of_date=2026-12-31&currency=SGD",
                      },
                    ],
                  },
                ],
      });
    }
    if (path.startsWith("/api/portfolio/holdings")) {
      if (path.includes("include_disposed=true"))
        return Promise.resolve({
          items: [mockHolding, mockHolding2],
          total: 2,
          warnings: [],
        });
      return Promise.resolve({
        items: holdings,
        total: holdings.length,
        warnings: [],
      });
    }
    return Promise.reject(new Error(`unhandled path ${path}`));
  });
}

describe("PortfolioPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  beforeEach(() => {
    mockedApiFetch.mockReset();
    showToastMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders page header and child components", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Portfolio")).toBeInTheDocument();
    expect(
      screen.getByText(/Track your investment holdings/),
    ).toBeInTheDocument();
    expect(screen.getByText("Update Prices")).toBeInTheDocument();
    expect(screen.getByTestId("performance-card")).toBeInTheDocument();
    expect(screen.getByTestId("allocation-chart-sector")).toBeInTheDocument();
    expect(
      screen.getByTestId("allocation-chart-geography"),
    ).toBeInTheDocument();
  });

  it("renders loading state while fetching holdings", () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/api/portfolio/summary")) return Promise.resolve({});
      return new Promise(() => {});
    });

    render(<PortfolioPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Loading holdings...")).toBeInTheDocument();
  });

  it("renders error state with retry button", async () => {
    mockedApiFetch.mockRejectedValue(new Error("network error"));

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("Failed to load holdings")).toBeInTheDocument(),
    );
    expect(screen.getByText("network error")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Retry loading holdings" }),
    );
    await waitFor(() =>
      expect(mockedApiFetch.mock.calls.length).toBeGreaterThan(2),
    );
  });

  it("renders empty state when no holdings", async () => {
    mockPortfolioApi([]);

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("No holdings found")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Upload brokerage statements/)).toBeInTheDocument();
  });

  it("renders holdings table when data is loaded", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText("IBKR")).toBeInTheDocument();
  });

  it("toggles show disposed checkbox and refetches with include_disposed", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Show disposed" }));

    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/portfolio/holdings?include_disposed=true",
    );
  });

  // AC-portfolio.fe-assets2.16
  it("AC17.9.3 passes selected as-of date to holdings API", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Portfolio as-of date"), {
      target: { value: "2025-01-31" },
    });

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/portfolio/holdings?as_of_date=2025-01-31",
      ),
    );

    fireEvent.click(screen.getByLabelText("Clear portfolio as-of date"));

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/portfolio/holdings"),
    );
  });

  it("has a link to the prices page", async () => {
    mockPortfolioApi([]);

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const link = screen.getByText("Update Prices").closest("a");
    expect(link).toHaveAttribute("href", "/portfolio/prices");
  });

  it("AC17.8.4 shows total portfolio value banner when active holdings are loaded", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByTestId("total-portfolio-value")).toBeInTheDocument(),
    );
    expect(screen.getByText("Total Portfolio Value")).toBeInTheDocument();
    expect(screen.getByTestId("total-portfolio-value")).toHaveTextContent(
      "1,800",
    );
  });

  // AC-portfolio.fe-assets2.24
  it("AC17.7.5 renders realized P&L YTD and dividend income YTD from portfolio summary", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("Realized P&L YTD")).toBeInTheDocument(),
    );
    expect(screen.getByText("Dividend Income YTD")).toBeInTheDocument();
    expect(screen.getAllByText("$149.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("$42.50").length).toBeGreaterThanOrEqual(1);
  });

  // AC-reporting.fe-viz-reports.2
  it("AC5.8.1 renders investment performance report schedule from the schedule API", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("investment_performance")).toBeInTheDocument(),
    );
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/portfolio/performance/report-schedule?currency=SGD",
    );
    expect(screen.getByText(/Report section/)).toBeInTheDocument();
    expect(screen.getByText("Source Links")).toBeInTheDocument();
    expect(screen.getByText("brokerage_statement:aapl")).toBeInTheDocument();
    expect(
      screen.getByText("Cost basis uses FIFO where available."),
    ).toBeInTheDocument();
  });

  // AC-portfolio.fe-assets2.18
  it("AC17.14.3 renders net-worth allocation from the report schedule", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/api/reports/net-worth/allocation?currency=SGD&include_restricted=true",
    );
    expect(
      within(panel).getByText("Asset Class x Liquidity x Source Currency"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Source currency")).toBeInTheDocument();
    expect(await within(panel).findByText("Net worth")).toBeInTheDocument();
    expect(await within(panel).findByText("Public Equity")).toBeInTheDocument();
    expect(within(panel).getAllByText("Liquid").length).toBeGreaterThanOrEqual(
      1,
    );
    expect(within(panel).getAllByText("USD").length).toBeGreaterThanOrEqual(1);
    expect(
      within(panel).getByRole("link", { name: "AAPL market value" }),
    ).toHaveAttribute("href", "/portfolio/holdings");
    expect(
      within(panel).getByText("Manual adjustment").closest("a"),
    ).toBeNull();
    expect(
      within(panel).getByText("Manual adjustment").closest("li"),
    ).toHaveAttribute("title", "Manual adjustment");
    expect(within(panel).getByText("Main Bank")).toBeInTheDocument();
    expect(within(panel).getByText("100.0%")).toBeInTheDocument();
    expect(within(panel).getByText("-5.0%")).toBeInTheDocument();
    expect(within(panel).getByText("2 sources")).toBeInTheDocument();
    expect(
      within(panel).getAllByText("1 source").length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("AC11.20.3 labels retirement and benefit assets in net-worth allocation", async () => {
    mockPortfolioApi([mockHolding], "100.00", "USD", "retirement_benefit");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(
      await within(panel).findByText("Retirement & Benefit Assets"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Restricted")).toBeInTheDocument();
    expect(
      within(panel).getByRole("link", { name: "401k statement" }),
    ).toHaveAttribute("href", "/assets/valuation-components");
  });

  it("AC17.14.3 shows the net-worth allocation loading state", () => {
    mockPortfolioApi([mockHolding], "100.00", "USD", "pending");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = screen.getByRole("region", { name: "Net Worth Allocation" });
    expect(
      within(panel).getByText("Loading net worth allocation..."),
    ).toBeInTheDocument();
  });

  it("AC17.14.3 shows the net-worth allocation error state", async () => {
    mockPortfolioApi([mockHolding], "100.00", "USD", "error");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(
      await within(panel).findByText("Unable to load net worth allocation"),
    ).toBeInTheDocument();
  });

  it("AC17.14.3 shows the empty net-worth allocation state", async () => {
    mockPortfolioApi([mockHolding], "100.00", "USD", "empty");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(
      await within(panel).findByText("No allocation rows available"),
    ).toBeInTheDocument();
  });

  // AC-portfolio.fe-assets2.17
  it("AC17.14.1 labels allocation and portfolio currencies instead of claiming a portfolio tie-out", async () => {
    mockPortfolioApi([mockHolding], "100.00", "SGD");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(within(panel).getByText("Report currency: SGD")).toBeInTheDocument();
    expect(await within(panel).findByText("Public Equity")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Portfolio value shown in USD");
    expect(
      within(panel).queryByText(/Ties to portfolio value/),
    ).not.toBeInTheDocument();
  });

  it("AC17.14.3 renders invalid net-worth allocation percentages as unavailable", async () => {
    mockPortfolioApi([mockHolding], "not-a-number");

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(await within(panel).findByText("Public Equity")).toBeInTheDocument();
    expect(within(panel).getByText("N/A")).toBeInTheDocument();
  });

  it("AC17.14.3 renders missing net-worth allocation percentages as unavailable", async () => {
    mockPortfolioApi([mockHolding], null);

    render(<PortfolioPage />, { wrapper: createWrapper() });

    const panel = await screen.findByRole("region", {
      name: "Net Worth Allocation",
    });
    expect(await within(panel).findByText("Public Equity")).toBeInTheDocument();
    expect(within(panel).getByText("N/A")).toBeInTheDocument();
  });

  it("AC17.14.3 refetches net-worth allocation when restricted holdings are excluded", async () => {
    mockPortfolioApi();

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await screen.findByRole("region", { name: "Net Worth Allocation" });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include restricted holdings in allocation",
      }),
    );

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/reports/net-worth/allocation?currency=SGD&include_restricted=false",
      ),
    );
  });

  it("AC17.8.4 does not show total portfolio value banner when no active holdings", async () => {
    mockPortfolioApi([]);

    render(<PortfolioPage />, { wrapper: createWrapper() });

    await waitFor(() =>
      expect(screen.getByText("No holdings found")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("total-portfolio-value"),
    ).not.toBeInTheDocument();
  });
});
