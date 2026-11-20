import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProcessingTransfers } from "@/components/reconciliation/ProcessingTransfers";
import { apiOperation } from "@/lib/api";
import { PROCESSING_PENDING_QUERY_KEY } from "@/lib/sharedQueries";
import { fTxt, has, OP } from "./helpers/statementTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const mockedApi = vi.mocked(apiOperation);
const xf = (id: string, from: string, to: string, amount: string, days: number) => ({ entry_id: id, from_account: from, to_account: to, amount, currency: "SGD", initiated_date: "2026-05-01", days_outstanding: days, description: id });

describe("ProcessingTransfers", () => {
  beforeEach(() => { mockedApi.mockReset(); });

  it("AC15.7.3/4 renders pending transfers, >7d warning, errors, and empty state", async () => {
    mockedApi.mockResolvedValueOnce({ items: [xf("e1", "Bank A", "Bank B", "500.00", 2), xf("e2", "Bank C", "Bank D", "1000.00", 12)], total: 2 } as never);
    const v1 = render(<ProcessingTransfers />);
    await waitFor(() => {
      expect(mockedApi).toHaveBeenCalledWith(OP.XFER_PEND, { query: { limit: 500, offset: 0 } });
      has(["Bank A", "Bank B", /500\.00/, "Bank C", "Bank D", /1,000\.00/]);
      expect(screen.getByLabelText(/warning/i)).toHaveTextContent("12d");
    });
    v1.unmount();

    mockedApi.mockRejectedValueOnce(new Error("processing unavailable"));
    const v2 = render(<ProcessingTransfers />);
    expect(await fTxt("processing unavailable")).toBeInTheDocument();
    v2.unmount();

    mockedApi.mockResolvedValueOnce({ items: [], total: 0 } as never);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={client}><ProcessingTransfers /></QueryClientProvider>);
    await waitFor(() => expect(client.getQueryState(PROCESSING_PENDING_QUERY_KEY)?.status).toBe("success"));
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Transfers in flight")).toBeNull();
  });
});
