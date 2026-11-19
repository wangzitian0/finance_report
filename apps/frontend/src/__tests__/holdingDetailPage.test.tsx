import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HoldingDetail } from "@/components/portfolio/Holdings";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/packageTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

describe("HoldingDetail drawer", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => { api.mockReset(); });

  it("renders loading, error retry, and not-found states", () => F.runHdErrorStates(api, HoldingDetail));

  it("AC17.7.1 AC17.7.2 AC17.7.3 AC17.7.4 AC17.7.6 renders tabs, lots, dividends, realized P&L, and updates cost basis", async () => {
    F.mockDetailApi(api, [{ ...F.HD_ACTIVE, quantity: "10.123456789" }, F.HD_DISPOSED]);
    render(<HoldingDetail ticker="AAPL" />);
    await waitFor(() => expect(screen.getAllByText("Market Value").length).toBeGreaterThanOrEqual(1));
    expect(api).toHaveBeenCalledWith("get_holdings_portfolio_holdings_get", { query: { include_disposed: true } });
    F.hasAny(F.HD_LABELS.sum); expect(F.txt(/Unrealized P&L/)).toBeInTheDocument();
    F.chg("Cost basis method", "LIFO");
    await F.wfCall(api, "update_holding_cost_basis_method_portfolio__ticker__patch", { path: { ticker: "AAPL" }, body: { cost_basis_method: "LIFO" } });
    expect(api).toHaveBeenCalledWith("get_holding_realized_lots_portfolio__ticker__realized_get", { path: { ticker: "AAPL" } });
    fireEvent.click(screen.getByRole("tab", { name: "Dividends" })); F.has(F.HD_LABELS.div);
    fireEvent.click(screen.getByRole("tab", { name: "Realized P&L" })); F.has(F.HD_LABELS.lot, F.txt("Realized P&L Lots").closest(".card") as HTMLElement);
  });
}); // AC-portfolio.fe-assets2.20 AC-portfolio.fe-assets2.21 AC-portfolio.fe-assets2.22 AC-portfolio.fe-assets2.23
