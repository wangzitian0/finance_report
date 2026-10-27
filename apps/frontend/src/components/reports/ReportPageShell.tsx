"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { SkeletonBlock } from "@/components/ui";
import { apiOperationDownload, type ApiOperationRequest } from "@/lib/api-client";
import type { FxWarning } from "@/lib/types";

function formatWarning(warning: FxWarning): string {
  if (warning.message) return warning.message;
  const from = warning.base_currency ?? warning.from_currency;
  const to = warning.quote_currency ?? warning.to_currency;
  const route = from && to ? `${from} to ${to}` : "FX conversion";
  const when = warning.rate_date ?? warning.date;
  const date = when ? ` on ${when}` : "";
  const fallback = warning.fallback_date ? `; using ${warning.fallback_date}` : "";
  return `${warning.type}: ${route}${date}${fallback}`;
}

export function FxWarningBanner({ warnings }: { warnings?: FxWarning[] }) {
  if (!warnings?.length) return null;
  return (
    <div className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm">
      <p className="font-medium text-[var(--warning)]">Partial FX data used</p>
      <ul className="mt-2 space-y-1 text-muted">
        {warnings.map((w) => (
          <li key={formatWarning(w)}>{formatWarning(w)}</li>
        ))}
      </ul>
    </div>
  );
}

const DEFAULT_OPENING_MSG =
  "Activity is recorded without an opening balance, so account totals reflect only period movement, not your actual starting balances. Record opening balances to trust these totals.";

export function OpeningBalanceWarningBanner({ warnings }: { warnings?: FxWarning[] }) {
  if (!warnings?.length) return null;
  const message = warnings.find((w) => w.message)?.message ?? DEFAULT_OPENING_MSG;
  return (
    <div role="alert" className="mb-6 rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-4 text-sm">
      <p className="font-medium text-[var(--warning)]">Opening balances not recorded</p>
      <p className="mt-1 text-muted">{message}</p>
      <Link href="/settings?tab=accounts" className="mt-2 inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline">
        Set opening balances →
      </Link>
    </div>
  );
}

export function ExportCsvButton({ request }: { request: ApiOperationRequest<"export_report_reports_export_get"> }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setDownloading(true);
    setError(null);
    try {
      const { blob, filename } = await apiOperationDownload("export_report_reports_export_get", request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "report.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export CSV.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button type="button" onClick={handleExport} disabled={downloading} className="btn-secondary text-sm">
        {downloading ? "Exporting..." : "Export CSV"}
      </button>
      {error && <span className="text-xs text-[var(--error)]">{error}</span>}
    </div>
  );
}

export function AiPromptAction({ prompt, label = "AI Interpretation" }: { prompt: string; label?: string }) {
  return (
    <Link href={`/chat?prompt=${encodeURIComponent(prompt)}`} className="btn-secondary text-sm">
      {label}
    </Link>
  );
}

export function ReportToolbar({
  aiPrompt,
  exportControl,
  children,
}: {
  aiPrompt: string;
  exportControl?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {children}
      <AiPromptAction prompt={aiPrompt} />
      {exportControl}
    </div>
  );
}

export function ReportPageSkeleton({ label, sections = 3 }: { label: string; sections?: number }) {
  return (
    <div role="status" aria-label={label} aria-live="polite" aria-busy="true">
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between" aria-hidden="true">
        <div className="space-y-2">
          <SkeletonBlock className="h-7 w-48" />
          <SkeletonBlock className="h-4 w-72 max-w-full" />
        </div>
        <div className="flex gap-2">
          <SkeletonBlock className="h-9 w-32" />
          <SkeletonBlock className="h-9 w-20" />
          <SkeletonBlock className="h-9 w-28" />
        </div>
      </div>
      <div className="mb-6 flex flex-wrap gap-3" aria-hidden="true">
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-28" />
      </div>
      <div className="mb-6 grid gap-4 md:grid-cols-3" aria-hidden="true">
        {Array.from({ length: 3 }).map((_, idx) => (
          <div key={idx} className="card p-5">
            <SkeletonBlock className="mb-3 h-3 w-24" />
            <SkeletonBlock className="h-7 w-32" />
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3" aria-hidden="true">
        {Array.from({ length: sections }).map((_, sIdx) => (
          <div key={sIdx} className="card p-5">
            <SkeletonBlock className="mb-4 h-5 w-36" />
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((__, rIdx) => (
                <div key={rIdx} className="flex items-center justify-between gap-4 rounded-control bg-surface-muted/50 p-2">
                  <SkeletonBlock className="h-4 w-2/5" />
                  <SkeletonBlock className="h-4 w-24" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReportPageShell({
  title,
  description,
  toolbar,
  loadingLabel,
  loadingSections,
  isLoading = false,
  isError = false,
  errorMessage,
  onRetry,
  children,
}: {
  title: string;
  description?: string;
  toolbar?: ReactNode;
  loadingLabel: string;
  loadingSections?: number;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (isLoading) return <ReportPageSkeleton label={loadingLabel} sections={loadingSections} />;
  if (isError) {
    return (
      <div className="card p-8 text-center max-w-md mx-auto">
        <p className="text-muted mb-4">{errorMessage ?? "Failed to load report."}</p>
        {onRetry && <button type="button" onClick={onRetry} className="btn-secondary">Retry</button>}
      </div>
    );
  }
  return (
    <section aria-label={title}>
      <div className="mb-6 flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">{title}</h2>
          {description && <p className="text-sm text-muted">{description}</p>}
        </div>
        {toolbar}
      </div>
      {children}
    </section>
  );
}
