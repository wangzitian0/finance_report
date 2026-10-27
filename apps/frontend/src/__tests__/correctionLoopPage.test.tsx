import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CorrectionLoopProof } from "@/components/audit/AuditPanels";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

describe("Correction loop proof", () => {
  beforeEach(() => mockedApiOperation.mockReset());

  it("renders held-out replay without a source-type confidence trend", async () => {
    mockedApiOperation.mockResolvedValue({
      holdout_size: 10,
      grounded: 4,
      proportion_before: "0.30000",
      proportion_after: "0.18000",
      reduced: true,
    });

    render(<CorrectionLoopProof />);

    expect(await screen.findByText("30.0%")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getByText("Improves extraction")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Correction Loop Proof" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/TraceRecord/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/posted facts/i)).not.toBeInTheDocument();
  });

  it("surfaces a retryable error", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      mockedApiOperation.mockRejectedValueOnce(new Error("offline"));
      mockedApiOperation.mockResolvedValueOnce({
        holdout_size: 10,
        grounded: 4,
        proportion_before: "0.30000",
        proportion_after: "0.18000",
        reduced: true,
      });
      render(<CorrectionLoopProof />);
      await waitFor(() =>
        expect(screen.getByText("Couldn't load correction-loop proof")).toBeInTheDocument(),
      );
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      expect(await screen.findByText("30.0%")).toBeInTheDocument();
      expect(mockedApiOperation).toHaveBeenCalledTimes(2);
    } finally {
      consoleError.mockRestore();
    }
  });
});
