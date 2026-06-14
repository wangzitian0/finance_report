"use client";

// #1003 / #1055 PR4: surface Axiom B's confidence loop in the UI.
//
// The backend already measures the loop — the North-Star low-confidence
// proportion and the held-out correction-loop replay — but until now those
// numbers were invisible to users. This page makes them legible: the current
// proportion prominently (lower is better), the recorded trend over time, and
// whether the correction loop measurably lowers the proportion.

import { useCallback, useEffect, useState } from "react";
import { TrendingDown, TrendingUp, Minus, ShieldCheck } from "lucide-react";

import { fetchConfidenceNorthStar, fetchCorrectionLoopReplay } from "@/lib/api";
import {
  formatProportionPercent,
  hasNoSnapshots,
  summarizeReplay,
  toSparklinePoints,
  trendDelta,
  type TrendDirection,
} from "@/lib/confidence";
import { formatDateTimeDisplay } from "@/lib/date";
import type {
  ConfidenceNorthStarResponse,
  CorrectionLoopReplayResponse,
} from "@/lib/types";
import { TrendChart } from "@/components/charts/TrendChart";
import { Badge, EmptyState, LoadingState, PageHeader } from "@/components/ui";

interface ConfidenceData {
  northStar: ConfidenceNorthStarResponse;
  replay: CorrectionLoopReplayResponse;
}

const DIRECTION_ICON: Record<TrendDirection, typeof TrendingDown> = {
  down: TrendingDown,
  up: TrendingUp,
  flat: Minus,
};

// Lower low-confidence proportion is better, so a "down" trend is the good news.
const DIRECTION_LABEL: Record<TrendDirection, string> = {
  down: "Trending down — fewer low-confidence facts",
  up: "Trending up — more low-confidence facts",
  flat: "Holding steady",
};

const DIRECTION_COLOR: Record<TrendDirection, string> = {
  down: "var(--success)",
  up: "var(--error)",
  flat: "var(--foreground-muted)",
};

export default function ConfidenceTrendPage() {
  const [data, setData] = useState<ConfidenceData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Reset to the loading state so a refresh/retry never shows stale numbers.
    setData(null);
    setError(null);
    try {
      const [northStar, replay] = await Promise.all([
        fetchConfidenceNorthStar(),
        fetchCorrectionLoopReplay(),
      ]);
      setData({ northStar, replay });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the confidence trend");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="p-6">
      <PageHeader
        title="Confidence Trend"
        description="The share of your posted data the system is least sure about — the low-confidence tail Axiom B works to shrink. Lower is better."
      />

      {data === null && !error && <LoadingState label="Loading the confidence trend" />}

      {error && (
        <EmptyState
          role="alert"
          title="Couldn't load the confidence trend"
          description={error}
          action={
            <button onClick={load} className="btn-secondary text-sm">
              Retry
            </button>
          }
        />
      )}

      {data !== null && !error && (
        <div className="space-y-6">
          <NorthStarCard data={data.northStar} />
          <ReplayCard replay={data.replay} />
        </div>
      )}
    </div>
  );
}

function NorthStarCard({ data }: { data: ConfidenceNorthStarResponse }) {
  const { current, series } = data;
  const { direction } = trendDelta(series);
  const DirectionIcon = DIRECTION_ICON[direction];
  const points = toSparklinePoints(series, (snapshot) =>
    formatDateTimeDisplay(snapshot.captured_at),
  );

  return (
    <section className="card p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="inline-flex items-center gap-2 font-semibold">
            <ShieldCheck className="h-4 w-4 text-[var(--accent)]" aria-hidden="true" />
            Low-confidence proportion
          </h2>
          <p className="mt-1 text-sm text-muted">
            {current.low_confidence_count} of {current.total_count} posted facts are low confidence.
          </p>
        </div>
        <div className="text-right">
          <p className="text-4xl font-semibold tabular-nums">
            {formatProportionPercent(current.low_confidence_proportion)}
          </p>
          {series.length >= 2 && (
            <p
              className="mt-1 inline-flex items-center justify-end gap-1 text-xs"
              style={{ color: DIRECTION_COLOR[direction] }}
            >
              <DirectionIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {DIRECTION_LABEL[direction]}
            </p>
          )}
        </div>
      </div>

      {hasNoSnapshots(data) || points.length === 0 ? (
        <EmptyState
          framed={false}
          className="mt-4"
          title="No trend recorded yet"
          description="The current proportion is shown above. A trend line appears here once snapshots accumulate."
        />
      ) : (
        <div className="mt-5">
          <TrendChart points={points} height={180} />
        </div>
      )}
    </section>
  );
}

function ReplayCard({ replay }: { replay: CorrectionLoopReplayResponse }) {
  const summary = summarizeReplay(replay);

  return (
    <section className="card p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">Correction-loop effect</h2>
        {summary.hasHoldout && (
          <Badge variant={summary.reduced ? "success" : "muted"}>
            {summary.reduced ? "Reduces low confidence" : "No measurable reduction"}
          </Badge>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        A held-out replay of your past corrections — does the loop measurably shrink the
        low-confidence proportion?
      </p>

      {summary.hasHoldout ? (
        <div className="mt-4 grid grid-cols-2 gap-3 text-center">
          <div className="rounded-md bg-[var(--background-muted)] p-3">
            <p className="text-2xl font-semibold tabular-nums">{summary.before}</p>
            <p className="mt-1 text-xs text-muted">Before the loop</p>
          </div>
          <div className="rounded-md bg-[var(--background-muted)] p-3">
            <p
              className="text-2xl font-semibold tabular-nums"
              style={{ color: summary.reduced ? "var(--success)" : undefined }}
            >
              {summary.after}
            </p>
            <p className="mt-1 text-xs text-muted">After the loop</p>
          </div>
        </div>
      ) : (
        <EmptyState
          framed={false}
          className="mt-4"
          title="Not enough correction history yet"
          description="Once you've corrected enough recurring items, the replay can hold some out and measure the loop's effect."
        />
      )}
    </section>
  );
}
