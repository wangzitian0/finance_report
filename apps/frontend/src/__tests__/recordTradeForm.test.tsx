import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecordTradeForm } from "@/components/portfolio/RecordTradeForm";
import { apiOperation } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

describe("RecordTradeForm", () => {
  const api = vi.mocked(apiOperation);

  beforeEach(() => {
    api.mockReset();
  });

  it("validates required inputs and submits POST /portfolio/trades via apiOperation", async () => {
    const onSuccess = vi.fn();
    api.mockResolvedValueOnce({} as never);

    render(<RecordTradeForm knownTickers={["AAPL", "VOO"]} defaultCurrency="USD" onSuccess={onSuccess} />);

    fireEvent.click(screen.getByRole("button", { name: "Submit trade" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/ticker/i);
    expect(api).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Trade side"), { target: { value: "SELL" } });
    fireEvent.change(screen.getByLabelText("Trade date"), { target: { value: "2026-02-15" } });
    fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: "aapl" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Unit price"), { target: { value: "150.00" } });
    fireEvent.change(screen.getByLabelText("Fees"), { target: { value: "2.00" } });
    fireEvent.change(screen.getByLabelText("Cost basis method"), { target: { value: "LIFO" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit trade" }));

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith("record_portfolio_trade_portfolio_trades_post", {
        body: {
          side: "SELL",
          transaction_date: "2026-02-15",
          asset_identifier: "AAPL",
          quantity: "4",
          unit_price: "150.00",
          currency: "USD",
          fees: "2.00",
          cost_basis_method: "LIFO",
        },
      });
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});
