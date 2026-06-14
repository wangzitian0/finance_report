import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConfidenceTrendPage from "@/app/(main)/confidence/page";
import { fetchConfidenceNorthStar, fetchCorrectionLoopReplay } from "@/lib/api";
import type {
  ConfidenceNorthStarResponse,
  CorrectionLoopReplayResponse,
} from "@/lib/types";

vi.mock("@/lib/api", () => ({
  fetchConfidenceNorthStar: vi.fn(),
  fetchCorrectionLoopReplay: vi.fn(),
}));

const mockedNorthStar = vi.mocked(fetchConfidenceNorthStar);
const mockedReplay = vi.mocked(fetchCorrectionLoopReplay);

function northStar(
  overrides: Partial<ConfidenceNorthStarResponse> = {},
): ConfidenceNorthStarResponse {
  return {
    current: {
      total_count: 200,
      low_confidence_count: 25,
      low_confidence_proportion: "0.12500",
      tier_breakdown: { LOW: 25, MEDIUM: 50, HIGH: 75, TRUSTED: 50 },
    },
    series: [
      {
        id: "s2",
        captured_at: "2026-06-10T00:00:00Z",
        total_count: 200,
        low_confidence_count: 25,
        low_confidence_proportion: "0.12500",
        tier_breakdown: {},
      },
      {
        id: "s1",
        captured_at: "2026-06-01T00:00:00Z",
        total_count: 180,
        low_confidence_count: 36,
        low_confidence_proportion: "0.20000",
        tier_breakdown: {},
      },
    ],
    ...overrides,
  };
}

function replay(
  overrides: Partial<CorrectionLoopReplayResponse> = {},
): CorrectionLoopReplayResponse {
  return {
    holdout_size: 10,
    grounded: 4,
    proportion_before: "0.30000",
    proportion_after: "0.18000",
    reduced: true,
    ...overrides,
  };
}

describe("Confidence Trend page (#1003 / #1055 PR4)", () => {
  beforeEach(() => {
    mockedNorthStar.mockReset();
    mockedReplay.mockReset();
  });

  it("renders the current proportion, the trend direction, and the replay effect", async () => {
    mockedNorthStar.mockResolvedValue(northStar());
    mockedReplay.mockResolvedValue(replay());

    render(<ConfidenceTrendPage />);

    // Decimal-string proportion "0.12500" formats as a percentage, shown prominently.
    expect(await screen.findByText("12.5%")).toBeInTheDocument();
    expect(screen.getByText(/25 of 200 posted facts/i)).toBeInTheDocument();

    // Newest (12.5%) is lower than previous (20%) — the good "trending down" news.
    expect(screen.getByText(/Trending down/i)).toBeInTheDocument();

    // Replay before -> after and the "reduces" verdict.
    expect(screen.getByText("30.0%")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getByText(/Reduces low confidence/i)).toBeInTheDocument();
  });

  it("shows an empty-trend state when no snapshots have been recorded yet", async () => {
    mockedNorthStar.mockResolvedValue(northStar({ series: [] }));
    mockedReplay.mockResolvedValue(replay({ holdout_size: 0, reduced: false }));

    render(<ConfidenceTrendPage />);

    await waitFor(() => expect(screen.getByText("No trend recorded yet")).toBeInTheDocument());
    // Current proportion is still shown even with no series.
    expect(screen.getByText("12.5%")).toBeInTheDocument();
    // No held-out split -> the replay can't draw a conclusion yet.
    expect(screen.getByText("Not enough correction history yet")).toBeInTheDocument();
  });

  it("surfaces a retryable error state when the metrics fail to load", async () => {
    mockedNorthStar.mockRejectedValue(new Error("offline"));
    mockedReplay.mockResolvedValue(replay());

    render(<ConfidenceTrendPage />);

    await waitFor(() =>
      expect(screen.getByText("Couldn't load the confidence trend")).toBeInTheDocument(),
    );
    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
