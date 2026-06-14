"use client";

export interface FxWarning {
  type: string;
  message?: string;
  from_currency?: string;
  to_currency?: string;
  date?: string;
  fallback_date?: string;
  source?: string;
  [key: string]: string | undefined;
}

function formatWarning(warning: FxWarning): string {
  if (warning.message) return warning.message;

  const route = warning.from_currency && warning.to_currency
    ? `${warning.from_currency} to ${warning.to_currency}`
    : "FX conversion";
  const date = warning.date ? ` on ${warning.date}` : "";
  const fallback = warning.fallback_date ? `; using ${warning.fallback_date}` : "";

  return `${warning.type}: ${route}${date}${fallback}`;
}

interface FxWarningBannerProps {
  warnings?: FxWarning[];
}

export function FxWarningBanner({ warnings }: FxWarningBannerProps) {
  if (!warnings?.length) return null;

  return (
    <div className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm">
      <p className="font-medium text-[var(--warning)]">Partial FX data used</p>
      <ul className="mt-2 space-y-1 text-muted">
        {warnings.map((warning) => (
          <li key={`${warning.type}:${warning.from_currency ?? ""}-${warning.to_currency ?? ""}:${warning.date ?? ""}:${warning.fallback_date ?? ""}`}>{formatWarning(warning)}</li>
        ))}
      </ul>
    </div>
  );
}
