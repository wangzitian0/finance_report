import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CorrectionLoopPage from "@/app/(main)/confidence/page";
import { fetchCorrectionLoopReplay } from "@/lib/api";

vi.mock("@/lib/api", () => ({ fetchCorrectionLoopReplay: vi.fn() }));

const mockedReplay = vi.mocked(fetchCorrectionLoopReplay);

describe("Correction loop proof page", () => {
  beforeEach(() => mockedReplay.mockReset());

  it("renders held-out replay without a source-type confidence trend", async () => {
    mockedReplay.mockResolvedValue({
      holdout_size: 10,
      grounded: 4,
      proportion_before: "0.30000",
      proportion_after: "0.18000",
      reduced: true,
    });

    render(<CorrectionLoopPage />);

    expect(await screen.findByText("30.0%")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getByText("Improves extraction")).toBeInTheDocument();
    expect(screen.queryByText(/posted facts/i)).not.toBeInTheDocument();
  });

  it("surfaces a retryable error", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      mockedReplay.mockRejectedValueOnce(new Error("offline"));
      mockedReplay.mockResolvedValueOnce({
        holdout_size: 10,
        grounded: 4,
        proportion_before: "0.30000",
        proportion_after: "0.18000",
        reduced: true,
      });
      render(<CorrectionLoopPage />);
      await waitFor(() =>
        expect(screen.getByText("Couldn't load correction-loop proof")).toBeInTheDocument(),
      );
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
      expect(await screen.findByText("30.0%")).toBeInTheDocument();
      expect(mockedReplay).toHaveBeenCalledTimes(2);
    } finally {
      consoleError.mockRestore();
    }
  });
});
