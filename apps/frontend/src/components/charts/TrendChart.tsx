import { useId } from "react";

interface TrendPoint {
  label: string;
  value: number;
}

interface TrendChartProps {
  points: TrendPoint[];
  height?: number;
}

const DEFAULT_HEIGHT = 220;

export function TrendChart({ points, height = DEFAULT_HEIGHT }: TrendChartProps) {
  const id = useId();
  const fillId = `trend-fill-${id}`;
  const lineId = `trend-line-${id}`;

  const values = points.map((point) => point.value);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;

  const width = 100;
  const chartHeight = 40;
  const padding = 8;

  const xStep = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;

  const coords = points.map((point, index) => {
    const x = padding + index * xStep;
    const y =
      chartHeight -
      padding -
      ((point.value - min) / span) * (chartHeight - padding * 2);
    return { x, y };
  });

  const linePath = coords
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`)
    .join(" ");

  const areaPath =
    `${linePath} L${padding + (points.length - 1) * xStep},${chartHeight - padding} ` +
    `L${padding},${chartHeight - padding} Z`;

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${width} ${chartHeight}`}
        className="w-full"
        style={{ height }}
        role="img"
        aria-label="Trend chart"
      >
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--chart-trend-start)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--chart-trend-end)" stopOpacity="0.05" />
          </linearGradient>
          <linearGradient id={lineId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--chart-trend-start)" />
            <stop offset="100%" stopColor="var(--chart-trend-end)" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${fillId})`} />
        <path
          d={linePath}
          fill="none"
          stroke={`url(#${lineId})`}
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        {coords.map((point, index) => (
          <circle
            key={`${points[index]?.label}-${index}`}
            cx={point.x}
            cy={point.y}
            r="1.4"
            fill="var(--chart-trend-start)"
          />
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--foreground-muted)]">
        {points.map((point, index) => (
          <span key={`${point.label}-${index}`} className="min-w-[3rem]">
            {point.label}
          </span>
        ))}
      </div>
    </div>
  );
}
