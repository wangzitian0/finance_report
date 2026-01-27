import { formatAmount } from "@/lib/currency";

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

export function BarChart({
  items,
  height = DEFAULT_HEIGHT,
  ariaLabel = "Income and expense comparison chart",
}: BarChartProps) {
  const maxValue = Math.max(
    ...items.flatMap((item) => [item.income, item.expense]),
    1
  );

  return (
    <div className="w-full" style={{ height }} role="img" aria-label={ariaLabel}>
      <div className="flex h-full items-end gap-4">
        {items.map((item) => {
          const incomeHeight = `${(item.income / maxValue) * 100}%`;
          const expenseHeight = `${(item.expense / maxValue) * 100}%`;
          return (
            <div key={item.label} className="flex flex-1 flex-col items-center gap-3">
              <div className="flex h-full w-full items-end justify-center gap-2">
                <div
                  className="w-3 rounded-full"
                  style={{ height: incomeHeight, backgroundColor: "var(--success)", opacity: 0.8, boxShadow: "0 0 14px color-mix(in srgb, var(--success) 35%, transparent)" }}
                  title={`Income ${formatAmount(item.income, 0)}`}
                />
                <div
                  className="w-3 rounded-full"
                  style={{ height: expenseHeight, backgroundColor: "var(--error)", opacity: 0.8, boxShadow: "0 0 14px color-mix(in srgb, var(--error) 35%, transparent)" }}
                  title={`Expense ${formatAmount(item.expense, 0)}`}
                />
              </div>
              <span className="text-xs text-[var(--foreground-muted)]">{item.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
