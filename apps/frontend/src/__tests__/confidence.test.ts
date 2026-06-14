import { describe, expect, it } from "vitest";

import {
  formatProportionPercent,
  hasNoSnapshots,
  summarizeReplay,
  toSparklinePoints,
  trendDelta,
} from "@/lib/confidence";
import type { ConfidenceMetricSnapshot } from "@/lib/types";

function snapshot(
  id: string,
  proportion: string,
  capturedAt = "2026-06-01T00:00:00Z",
): ConfidenceMetricSnapshot {
  return {
    id,
    captured_at: capturedAt,
    total_count: 100,
    low_confidence_count: 10,
    low_confidence_proportion: proportion,
    tier_breakdown: {},
  };
}

describe("confidence helpers (#1003 / #1055 PR4)", () => {
  describe("formatProportionPercent", () => {
    it("formats a Decimal-string proportion as a percentage", () => {
      expect(formatProportionPercent("0.12500")).toBe("12.5%");
      expect(formatProportionPercent("0")).toBe("0.0%");
      expect(formatProportionPercent("1")).toBe("100.0%");
    });

    it("renders an em dash for non-finite/missing values rather than NaN%", () => {
      expect(formatProportionPercent("")).toBe("—");
      expect(formatProportionPercent("not-a-number")).toBe("—");
    });
  });

  describe("trendDelta", () => {
    it("reports 'down' when the newest proportion is lower than the previous", () => {
      const result = trendDelta([snapshot("b", "0.10"), snapshot("a", "0.20")]);
      expect(result.direction).toBe("down");
      expect(result.delta).toBeCloseTo(-0.1);
    });

    it("reports 'up' when the newest proportion is higher", () => {
      expect(trendDelta([snapshot("b", "0.30"), snapshot("a", "0.20")]).direction).toBe("up");
    });

    it("is flat with fewer than two points or no change", () => {
      expect(trendDelta([]).direction).toBe("flat");
      expect(trendDelta([snapshot("a", "0.20")]).direction).toBe("flat");
      expect(trendDelta([snapshot("b", "0.20"), snapshot("a", "0.20")]).direction).toBe("flat");
    });
  });

  describe("toSparklinePoints", () => {
    it("reverses newest-first into oldest-first percentage points", () => {
      const points = toSparklinePoints(
        [snapshot("new", "0.10"), snapshot("old", "0.20")],
        (s) => s.id,
      );
      expect(points.map((p) => p.label)).toEqual(["old", "new"]);
      expect(points.map((p) => p.value)).toEqual([20, 10]);
    });
  });

  describe("summarizeReplay", () => {
    it("summarises the before/after percentages and reduction verdict", () => {
      const summary = summarizeReplay({
        holdout_size: 8,
        grounded: 3,
        proportion_before: "0.30000",
        proportion_after: "0.18000",
        reduced: true,
      });
      expect(summary).toEqual({ reduced: true, before: "30.0%", after: "18.0%", hasHoldout: true });
    });

    it("flags an empty held-out split as no conclusion yet", () => {
      const summary = summarizeReplay({
        holdout_size: 0,
        grounded: 0,
        proportion_before: "0",
        proportion_after: "0",
        reduced: false,
      });
      expect(summary.hasHoldout).toBe(false);
    });
  });

  describe("hasNoSnapshots", () => {
    it("is true only when the series is empty", () => {
      expect(hasNoSnapshots({ current: snapshot("c", "0.1"), series: [] })).toBe(true);
      expect(
        hasNoSnapshots({ current: snapshot("c", "0.1"), series: [snapshot("a", "0.1")] }),
      ).toBe(false);
    });
  });
});
