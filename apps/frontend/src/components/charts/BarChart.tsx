import { formatAmount } from "@/lib/audit/money";

interface BarItem {
  label: string;
  income: number;
  expense: number;
}

interface BarChartProps {
  items: BarItem[];
  height?: number;
  ariaLabel?: string;
}

const DEFAULT_HEIGHT = 220;

export function formatCompactChartValue(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) {
    return `${sign}${(abs / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    return `${sign}${(abs / 1_000).toFixed(1)}k`;
  }
  return `${sign}${formatAmount(abs, 0)}`;
}

export function BarChart({
  items,
  height = DEFAULT_HEIGHT,
  ariaLabel = "Income and expense comparison chart",
}: BarChartProps) {
  const maxValue = Math.max(
    ...items.flatMap((item) => [item.income, item.expense]),
    1
  );
  const midValue = maxValue / 2;

  return (
    <div className="w-full" style={{ height }} role="img" aria-label={ariaLabel}>
      <div className="flex h-full gap-3">
        <div
          className="flex flex-col justify-between py-1 text-[11px] text-[var(--foreground-muted)] select-none"
          data-testid="bar-chart-axis-scale"
        >
          <span>{formatCompactChartValue(maxValue)}</span>
          <span>{formatCompactChartValue(midValue)}</span>
          <span>0</span>
        </div>
        <div className="flex flex-1 h-full items-end gap-4 border-b border-l border-[var(--border)] pl-3 pb-1">
          {items.map((item) => {
            const incomeHeight = `${Math.max((item.income / maxValue) * 100, item.income > 0 ? 4 : 0)}%`;
            const expenseHeight = `${Math.max((item.expense / maxValue) * 100, item.expense > 0 ? 4 : 0)}%`;
            const net = item.income - item.expense;
            const netSign = net > 0 ? "+" : "";
            return (
              <div key={item.label} className="flex flex-1 flex-col items-center h-full justify-end gap-1.5">
                <span
                  className="text-[10px] font-medium text-[var(--foreground-muted)]"
                  data-testid={`bar-chart-net-${item.label}`}
                >
                  {`${netSign}${formatCompactChartValue(net)}`}
                </span>
                <div className="flex flex-1 w-full items-end justify-center gap-2">
                  <div
                    className="w-3.5 rounded-t-sm transition-all"
                    style={{
                      height: incomeHeight,
                      backgroundColor: "var(--success)",
                      opacity: 0.85,
                      boxShadow: "0 0 14px color-mix(in srgb, var(--success) 35%, transparent)",
                    }}
                    title={`Income ${formatAmount(item.income, 0)}`}
                  />
                  <div
                    className="w-3.5 rounded-t-sm transition-all"
                    style={{
                      height: expenseHeight,
                      backgroundColor: "var(--error)",
                      opacity: 0.85,
                      boxShadow: "0 0 14px color-mix(in srgb, var(--error) 35%, transparent)",
                    }}
                    title={`Expense ${formatAmount(item.expense, 0)}`}
                  />
                </div>
                <span className="text-xs text-[var(--foreground-muted)]">{item.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
