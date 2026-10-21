import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ProcessingSummaryCard } from "@/components/audit/TrustScoreHero";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
import { apiOperation } from "@/lib/api-client";

describe("ProcessingSummaryCard", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows error when apiOperation throws an Error", async () => {
        vi.mocked(apiOperation).mockRejectedValueOnce(new Error("boom"));
        render(<ProcessingSummaryCard />);
        await waitFor(() => expect(screen.getByText(/Error loading data/i)).toBeInTheDocument());
    });

    it("shows error when apiOperation rejects with non-Error value", async () => {
        vi.mocked(apiOperation).mockImplementationOnce(() => Promise.reject("not-an-error") as Promise<never>);
        render(<ProcessingSummaryCard />);
        await waitFor(() => expect(screen.getByText(/Error loading data/i)).toBeInTheDocument());
    });

    it("shows the current Processing Account balance when transfers are unresolved", async () => {
        vi.mocked(apiOperation).mockResolvedValueOnce({
            pending_count: 1,
            pending_total: "125.50",
            current_balance: "125.50",
            currency: "SGD",
            oldest_pending_date: "2026-05-01",
        });

        render(<ProcessingSummaryCard />);

        await waitFor(() => {
            expect(screen.getByTestId("processing-balance")).toHaveTextContent(/125\.50/);
            expect(screen.getByLabelText(/unresolved processing account balance/i)).toBeInTheDocument();
        });
    });

    it("shows a balanced state when the Processing Account balance is zero", async () => {
        vi.mocked(apiOperation).mockResolvedValueOnce({
            pending_count: 0,
            pending_total: "0.00",
            current_balance: "0.00",
            currency: "SGD",
            oldest_pending_date: null,
        });

        render(<ProcessingSummaryCard />);

        await waitFor(() => {
            expect(screen.getByTestId("processing-balance")).toHaveTextContent(/0\.00/);
            expect(screen.getByText("Balanced")).toBeInTheDocument();
        });
        expect(screen.queryByLabelText(/unresolved processing account balance/i)).not.toBeInTheDocument();
    });
});
