interface SankeyChartProps {
  title?: string;
  description?: string;
}

export function SankeyChart({
  title = "Flow overview",
  description = "Sankey visualization is planned for phase 2.",
}: SankeyChartProps) {
  return (
    <div className="rounded-3xl border border-dashed border-amber-300/70 bg-amber-50/60 p-6 text-center text-sm text-amber-800">
      <p className="text-base font-semibold">{title}</p>
      <p className="mt-2 text-xs leading-relaxed text-amber-700">{description}</p>
    </div>
  );
}
