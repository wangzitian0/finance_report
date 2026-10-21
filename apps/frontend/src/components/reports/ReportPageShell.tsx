"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { SkeletonBlock } from "@/components/ui";
import { apiOperationDownload, type ApiOperationRequest } from "@/lib/api-client";

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
  const route = warning.from_currency && warning.to_currency ? `${warning.from_currency} to ${warning.to_currency}` : "FX conversion";
  const date = warning.date ? ` on ${warning.date}` : "";
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
          <li key={`${w.type}:${w.from_currency ?? ""}-${w.to_currency ?? ""}:${w.date ?? ""}:${w.fallback_date ?? ""}`}>{formatWarning(w)}</li>
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
      <Link href="/accounts" className="mt-2 inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline">
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
  homeHref = "/",
  children,
}: {
  aiPrompt: string;
  exportControl?: ReactNode;
  homeHref?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex gap-2 flex-wrap">
      {children}
      <AiPromptAction prompt={aiPrompt} />
      <Link href={homeHref} className="btn-secondary text-sm">Home</Link>
      {exportControl}
    </div>
  );
}

export function ReportPageSkeleton({ label, sections = 3 }: { label: string; sections?: number }) {
  return (
    <div className="p-6" role="status" aria-label={label} aria-live="polite" aria-busy="true">
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
      <div className="p-6">
        <div className="card p-8 text-center max-w-md mx-auto">
          <p className="text-muted mb-4">{errorMessage ?? "Failed to load report."}</p>
          {onRetry && <button type="button" onClick={onRetry} className="btn-secondary">Retry</button>}
        </div>
      </div>
    );
  }
  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <h1 className="page-title">{title}</h1>
          {description && <p className="page-description">{description}</p>}
        </div>
        {toolbar}
      </div>
      {children}
    </div>
  );
}
