import { describe, expect, it } from "vitest";

import {
  hasNoSnapshots,
  parseProportion,
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
  describe("parseProportion", () => {
    it("returns null for null/undefined/blank/non-numeric/number and parses Decimal strings", () => {
      expect(parseProportion(null)).toBeNull();
      expect(parseProportion(undefined)).toBeNull();
      expect(parseProportion("  ")).toBeNull();
      expect(parseProportion("abc")).toBeNull();
      expect(parseProportion("0.25")).toBe(0.25);
      expect(parseProportion(0.5 as never)).toBeNull();
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

    it("drops blank-proportion snapshots instead of charting a bogus 0%", () => {
      const points = toSparklinePoints(
        [snapshot("new", "0.10"), snapshot("blank", "  "), snapshot("old", "0.20")],
        (s) => s.id,
      );
      expect(points.map((p) => p.label)).toEqual(["old", "new"]);
      expect(points.map((p) => p.value)).toEqual([20, 10]);
    });
  });

  describe("blank/missing-proportion guards", () => {
    it("trendDelta stays flat when an endpoint proportion is blank (no false 'down')", () => {
      expect(trendDelta([snapshot("new", "  "), snapshot("old", "0.20")]).direction).toBe("flat");
      expect(trendDelta([snapshot("new", "0.10"), snapshot("old", "")]).direction).toBe("flat");
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
