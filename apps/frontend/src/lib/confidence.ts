// #1003 / #1055 PR4: make Axiom B's confidence loop visible to users.
//
// The backend already measures the loop — the North-Star low-confidence
// proportion (EPIC-018 AC18.12) and the correction-loop replay (AC18.14) — but
// those numbers live only in API responses. This module holds the pure, testable
// glue the Confidence Trend view uses to turn the raw Decimal-string proportions
// into something legible: a percentage, a direction, and the trend's framing
// that "lower is better".

import type {
  ConfidenceMetricSnapshot,
  ConfidenceNorthStarResponse,
  CorrectionLoopReplayResponse,
} from "@/lib/types";
import {
  formatPercentFromRatioValue,
  percentNumberFromRatioValue,
  ratioNumberFromRatioValue,
} from "@/lib/ratio/format";

/**
 * Parse a proportion to a finite number, or `null` for a missing/blank/non-finite
 * value. `Number("")` and `Number("  ")` coerce to 0, so blank strings must be
 * rejected explicitly rather than silently treated as 0.
 */
export function parseProportion(value: string | null | undefined): number | null {
  return ratioNumberFromRatioValue(value);
}

/**
 * Format a Decimal proportion string (e.g. "0.12500") as a percentage label
 * (e.g. "12.5%"). Proportions arrive as strings to preserve precision, so we
 * parse with Number only at the display boundary. A non-finite or missing
 * value renders as an em dash rather than "NaN%".
 */
export function formatProportionPercent(value: string, decimals = 1): string {
  return formatPercentFromRatioValue(value, { dp: decimals });
}

export type TrendDirection = "down" | "up" | "flat";

export interface TrendDelta {
  /** Movement of the most recent point relative to the previous one. */
  direction: TrendDirection;
  /** Absolute change in proportion (newest minus previous), as a fraction. */
  delta: number;
}

/**
 * Compare the two newest points in a newest-first series. Lower proportion is
 * better, so a "down" direction is the good news the view should celebrate.
 * Fewer than two points means there is nothing to compare yet ("flat", 0).
 */
export function trendDelta(series: ConfidenceMetricSnapshot[]): TrendDelta {
  if (series.length < 2) return { direction: "flat", delta: 0 };
  const newest = parseProportion(series[0]?.low_confidence_proportion);
  const previous = parseProportion(series[1]?.low_confidence_proportion);
  // A blank/missing endpoint means there is nothing trustworthy to compare.
  if (newest === null || previous === null) return { direction: "flat", delta: 0 };
  const delta = newest - previous;
  if (delta === 0) return { direction: "flat", delta: 0 };
  return { direction: delta < 0 ? "down" : "up", delta };
}

export interface SparklinePoint {
  label: string;
  /** Proportion as a percentage number (0–100) for charting. */
  value: number;
}

/**
 * Turn the newest-first series into oldest-first points for a left-to-right
 * sparkline/trend, mapping each Decimal-string proportion to a 0–100 percentage.
 */
export function toSparklinePoints(
  series: ConfidenceMetricSnapshot[],
  labelFor: (snapshot: ConfidenceMetricSnapshot) => string,
): SparklinePoint[] {
  return [...series]
    .reverse()
    .map((snapshot) => ({
      label: labelFor(snapshot),
      proportion: parseProportion(snapshot.low_confidence_proportion),
    }))
    // Drop blank/non-finite points so a missing value can't inject a bogus 0% datapoint.
    .filter((point): point is { label: string; proportion: number } => point.proportion !== null)
    .map((point) => ({ label: point.label, value: percentNumberFromRatioValue(String(point.proportion)) ?? 0 }));
}

export interface ReplaySummary {
  reduced: boolean;
  before: string;
  after: string;
  /** True once the corpus is large enough to have a held-out split to replay. */
  hasHoldout: boolean;
}

/**
 * Summarise the replay for display: whether the loop measurably reduced the
 * proportion, and the before→after percentages. An empty held-out split means
 * there isn't enough correction history to draw a conclusion yet.
 */
export function summarizeReplay(replay: CorrectionLoopReplayResponse): ReplaySummary {
  return {
    reduced: replay.reduced,
    before: formatProportionPercent(replay.proportion_before),
    after: formatProportionPercent(replay.proportion_after),
    hasHoldout: replay.holdout_size > 0,
  };
}

/** True when the North-Star has no recorded snapshots yet (empty trend). */
export function hasNoSnapshots(data: ConfidenceNorthStarResponse): boolean {
  return data.series.length === 0;
}
