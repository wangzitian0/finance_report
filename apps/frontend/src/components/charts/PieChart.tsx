interface PieSegment {
  label: string;
  value: number;
  color: string;
}

interface PieChartProps {
  segments: PieSegment[];
  size?: number;
}

const DEFAULT_SIZE = 180;

export function PieChart({ segments, size = DEFAULT_SIZE }: PieChartProps) {
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
          <circle r="42" fill="#fffaf0" />
        </g>
        <text
          x="80"
          y="80"
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-slate-700 text-xs font-semibold"
        >
          Assets
        </text>
      </svg>
      <div className="grid w-full grid-cols-2 gap-2 text-xs text-slate-600">
        {filtered.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: segment.color }}
            />
            <span className="truncate">{segment.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
