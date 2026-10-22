"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { useApiQuery } from "@/hooks/useApiQuery";
import { amountToChartNumber, formatCurrencyLocale } from "@/lib/audit/money";
import { formatMonthLabel } from "@/lib/date";
import type { NetWorthTimeSeriesResponse } from "@/lib/types";

// ECharts loads only when a chart renders, so a page without this chart does not carry it.
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

/** A period up to this many days draws one point per day. A longer period draws one point per month. */
const DAILY_GRANULARITY_MAX_DAYS = 92;
const DAY_MS = 24 * 60 * 60 * 1000;

function granularityFor(from: string, to: string): "daily" | "monthly" {
  const days = (Date.parse(to) - Date.parse(from)) / DAY_MS;
  return days <= DAILY_GRANULARITY_MAX_DAYS ? "daily" : "monthly";
}

// A revisit of the tab or of a period within this time reuses the cached series (#2583).
const NET_WORTH_SERIES_STALE_TIME_MS = 60_000;

/** The net worth history of the dimension-bar period (#2621 LC). The bar is the only period control. */
export function NetWorthTimeSeriesChart({ from, to, currency }: { from: string; to: string; currency?: string }) {
  const granularity = granularityFor(from, to);
  const seriesQuery = useApiQuery(
    ["report", "net-worth-timeseries", from, to, granularity, currency ?? ""],
    "net_worth_timeseries_reports_net_worth_timeseries_get",
    { query: { from, to, granularity, currency } },
    { staleTime: NET_WORTH_SERIES_STALE_TIME_MS },
  );
  const data: NetWorthTimeSeriesResponse | undefined = seriesQuery.data;
  const loading = seriesQuery.isPending;
  const error = seriesQuery.error
    ? seriesQuery.error.message || "Failed to load net worth history."
    : null;

  const points = useMemo(() => data?.points ?? [], [data?.points]);
  const option = useMemo(() => {
    const labels = points.map((point) =>
      data?.granularity === "monthly"
        ? formatMonthLabel(point.date)
        : point.date.slice(5),
    );
    const values = points.map((point) => amountToChartNumber(point.net_worth));
    return {
      grid: { left: 48, right: 18, top: 24, bottom: 32 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number) =>
          formatCurrencyLocale(value, data?.currency ?? "SGD"),
      },
      xAxis: { type: "category", data: labels, boundaryGap: false },
      yAxis: { type: "value" },
      series: [
        {
          name: "Net Worth",
          type: "line",
          smooth: true,
          showSymbol: false,
          data: values,
          lineStyle: { color: "#2563eb", width: 2 },
          areaStyle: { color: "rgba(37, 99, 235, 0.10)" },
        },
      ],
    };
  }, [data?.currency, data?.granularity, points]);

  return (
    <section className="card p-5" aria-label="Net worth time-series">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-muted uppercase tracking-wide">
            Net Worth History
          </p>
          <h3 className="font-semibold mt-1">{granularity === "daily" ? "Daily net worth" : "Monthly net worth"}</h3>
        </div>
      </div>
      {loading ? (
        <p className="text-sm text-muted">Loading net worth history...</p>
      ) : error ? (
        <p className="text-sm text-[var(--error)]">{error}</p>
      ) : points.length < 2 ? (
        <p className="text-sm text-muted">
          At least two net worth points are needed to draw a line.
        </p>
      ) : (
        <div data-testid="net-worth-echarts">
          <ReactECharts
            option={option}
            style={{ height: 260, width: "100%" }}
            notMerge
            lazyUpdate
          />
        </div>
      )}
    </section>
  );
}
