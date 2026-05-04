import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ProcessingSummaryCard from "@/components/ProcessingSummaryCard";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/lib/api";

describe("ProcessingSummaryCard", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows error when apiFetch throws an Error", async () => {
        vi.mocked(apiFetch).mockRejectedValueOnce(new Error("boom"));
        render(<ProcessingSummaryCard />);
        await waitFor(() => expect(screen.getByText(/Error loading data/i)).toBeInTheDocument());
    });

    it("shows error when apiFetch rejects with non-Error value", async () => {
        vi.mocked(apiFetch).mockImplementationOnce(() => Promise.reject("not-an-error") as Promise<never>);
        render(<ProcessingSummaryCard />);
        await waitFor(() => expect(screen.getByText(/Error loading data/i)).toBeInTheDocument());
    });
});
