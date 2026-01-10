interface BarItem {
  label: string;
  income: number;
  expense: number;
}

interface BarChartProps {
  items: BarItem[];
  height?: number;
}

const DEFAULT_HEIGHT = 220;

export function BarChart({ items, height = DEFAULT_HEIGHT }: BarChartProps) {
  const maxValue = Math.max(
    ...items.flatMap((item) => [item.income, item.expense]),
    1
  );

  return (
    <div className="w-full" style={{ height }}>
      <div className="flex h-full items-end gap-4">
        {items.map((item) => {
          const incomeHeight = `${(item.income / maxValue) * 100}%`;
          const expenseHeight = `${(item.expense / maxValue) * 100}%`;
          return (
            <div key={item.label} className="flex flex-1 flex-col items-center gap-3">
              <div className="flex h-full w-full items-end justify-center gap-2">
                <div
                  className="w-3 rounded-full bg-emerald-400/80 shadow-[0_0_14px_rgba(16,185,129,0.35)]"
                  style={{ height: incomeHeight }}
                  title={`Income ${item.income.toFixed(0)}`}
                />
                <div
                  className="w-3 rounded-full bg-rose-400/80 shadow-[0_0_14px_rgba(244,63,94,0.35)]"
                  style={{ height: expenseHeight }}
                  title={`Expense ${item.expense.toFixed(0)}`}
                />
              </div>
              <span className="text-xs text-slate-500">{item.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
