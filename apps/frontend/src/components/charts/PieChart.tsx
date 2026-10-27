import { formatCompactChartValue } from "@/components/charts/BarChart";

interface PieSegment {
  label: string;
  value: number;
  color: string;
}

interface PieChartProps {
  segments: PieSegment[];
  size?: number;
  centerLabel?: string;
  showLegend?: boolean;
}

const DEFAULT_SIZE = 180;

export function PieChart({
  segments,
  size = DEFAULT_SIZE,
  centerLabel = "Assets",
  showLegend = true,
}: PieChartProps) {
  const filtered = segments.filter((segment) => segment.value > 0);
  const total = filtered.reduce((sum, segment) => sum + segment.value, 0);
  const radius = 60;
  const circumference = 2 * Math.PI * radius;

  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 160 160" role="img" aria-label="Pie chart">
        <g transform="translate(80,80)">
          {filtered.map((segment) => {
            const fraction = total ? segment.value / total : 0;
            const dash = fraction * circumference;
            const dashArray = `${dash} ${circumference - dash}`;
            const dashOffset = offset;
            offset -= dash;
            return (
              <circle
                key={segment.label}
                r={radius}
                fill="transparent"
                stroke={segment.color}
                strokeWidth="18"
                strokeDasharray={dashArray}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
              />
            );
          })}
          <circle r="42" fill="var(--background-card)" />
        </g>
        <text
          x="80"
          y="80"
          textAnchor="middle"
          dominantBaseline="middle"
          className="text-xs font-semibold"
          style={{ fill: "var(--foreground)" }}
        >
          {centerLabel}
        </text>
      </svg>
      {showLegend ? (
        <div className="grid w-full grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-[var(--foreground-muted)]">
          {filtered.map((segment) => {
            const pct = total > 0 ? Math.round((segment.value / total) * 100) : 0;
            return (
              <div key={segment.label} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 bg-[var(--background-muted)]/50">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: segment.color }}
                  />
                  <span className="truncate">{segment.label}</span>
                </div>
                <span
                  className="shrink-0 font-medium text-[var(--foreground)]"
                  data-testid={`pie-segment-share-${segment.label}`}
                >
                  {`${pct}% · ${formatCompactChartValue(segment.value)}`}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
      <table className="sr-only">
        <caption>Chart data</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td>{item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
