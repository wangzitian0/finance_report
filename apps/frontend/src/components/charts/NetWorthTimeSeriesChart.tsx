"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";

import { apiFetch } from "@/lib/api";
import { amountToChartNumber, formatCurrencyLocale } from "@/lib/money";
import { formatDateInput, formatMonthLabel } from "@/lib/date";
import type { NetWorthRange, NetWorthTimeSeriesResponse } from "@/lib/types";

const RANGE_OPTIONS: NetWorthRange[] = ["1M", "3M", "6M", "1Y", "All"];

function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, date.getDate());
}

function getRangeParams(range: NetWorthRange): { from: string; granularity: "daily" | "monthly" } {
  const today = new Date();
  if (range === "All") {
    return { from: "1970-01-01", granularity: "monthly" };
  }
  const months = range === "1M" ? -1 : range === "3M" ? -3 : range === "6M" ? -6 : -12;
  return { from: formatDateInput(addMonths(today, months)), granularity: "daily" };
}

export function NetWorthTimeSeriesChart() {
  const [range, setRange] = useState<NetWorthRange>("6M");
  const [data, setData] = useState<NetWorthTimeSeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchSeries = useCallback(async () => {
    const params = getRangeParams(range);
    const to = formatDateInput(new Date());
    setLoading(true);
    try {
      const response = await apiFetch<NetWorthTimeSeriesResponse>(
        `/api/reports/net-worth/timeseries?from=${params.from}&to=${to}&granularity=${params.granularity}`,
      );
      setData(response);
      setError(null);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "Failed to load net worth history.");
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    fetchSeries();
  }, [fetchSeries]);

  const points = useMemo(() => data?.points ?? [], [data?.points]);
  const option = useMemo(() => {
    const labels = points.map((point) =>
      data?.granularity === "monthly" ? formatMonthLabel(point.date) : point.date.slice(5),
    );
    const values = points.map((point) => amountToChartNumber(point.net_worth));
    return {
      grid: { left: 48, right: 18, top: 24, bottom: 32 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number) => formatCurrencyLocale(value, data?.currency ?? "SGD"),
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
          lineStyle: { color: "var(--chart-trend-start)", width: 2 },
          areaStyle: { color: "rgba(37, 99, 235, 0.10)" },
        },
      ],
    };
  }, [data?.currency, data?.granularity, points]);

  return (
    <section className="card p-5" aria-label="Net worth time-series">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-muted uppercase tracking-wide">Net Worth History</p>
          <h3 className="font-semibold mt-1">Daily net worth</h3>
        </div>
        <div className="flex gap-1 bg-[var(--background-muted)] p-1 rounded-lg w-fit" role="tablist" aria-label="Net worth range">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={range === option}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                range === option ? "bg-[var(--background-card)]" : "text-muted hover:text-[var(--foreground)]"
              }`}
              onClick={() => setRange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <p className="text-sm text-muted">Loading net worth history...</p>
      ) : error ? (
        <p className="text-sm text-[var(--error)]">{error}</p>
      ) : points.length < 2 ? (
        <p className="text-sm text-muted">At least two net worth points are needed to draw a line.</p>
      ) : (
        <div data-testid="net-worth-echarts">
          <ReactECharts option={option} style={{ height: 260, width: "100%" }} notMerge lazyUpdate />
        </div>
      )}
    </section>
  );
}
