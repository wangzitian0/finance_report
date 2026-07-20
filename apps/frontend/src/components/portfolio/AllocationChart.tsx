"use client";

import { useQuery } from "@tanstack/react-query";
import { apiOperation } from "@/lib/api-client";
import {
  formatPercentFromPercentValue,
  percentNumberFromPercentValue,
} from "@/lib/audit/ratio/format";
import { AllocationBreakdown } from "@/lib/types";
import { PieChart } from "@/components/charts/PieChart";

const CHART_PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

type AllocationType = "sector" | "geography" | "asset-class";

const ALLOCATION_OPERATIONS = {
  sector: "get_sector_allocation_portfolio_allocation_sector_get",
  geography: "get_geography_allocation_portfolio_allocation_geography_get",
  "asset-class":
    "get_asset_class_allocation_portfolio_allocation_asset_class_get",
} as const;

interface AllocationChartProps {
  type: AllocationType;
  title: string;
}

const LABELS: Record<AllocationType, string> = {
  sector: "Sector",
  geography: "Geography",
  "asset-class": "Asset Class",
};

export function AllocationChart({ type, title }: AllocationChartProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio-allocation", type],
    queryFn: () => apiOperation(ALLOCATION_OPERATIONS[type]),
  });

  if (isLoading) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <div className="flex items-center justify-center py-8">
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin text-muted" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <p className="text-sm text-muted">Unable to load allocation data</p>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide mb-3">
          {title}
        </p>
        <p className="text-sm text-muted">No allocation data available</p>
      </div>
    );
  }

  const segments = data.map((d, i) => ({
    label: d.category || "Unknown",
    value: percentNumberFromPercentValue(d.percentage, { fallback: 0 }) ?? 0,
    color: CHART_PALETTE[i % CHART_PALETTE.length],
  }));

  return (
    <div className="card p-5">
      <p className="text-xs text-muted uppercase tracking-wide mb-3">{title}</p>
      <PieChart segments={segments} centerLabel={LABELS[type]} />
      <div className="mt-4 space-y-1.5">
        {data.map((d, i) => (
          <div
            key={d.category}
            className="flex items-center justify-between text-sm"
          >
            <div className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{
                  backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length],
                }}
              />
              <span className="truncate">{d.category || "Unknown"}</span>
              <span className="text-xs text-muted">({d.count})</span>
            </div>
            <span className="font-medium">
              {formatPercentFromPercentValue(d.percentage, { dp: 1 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
