"use client";

import type { ReactNode } from "react";

import { ReportPageSkeleton } from "@/components/reports/ReportPageSkeleton";

/**
 * Report page shell (Slice 3 of #751).
 *
 * Owns the header (title + description + toolbar slot) and the loading / error
 * lifecycle that every report route repeated by hand. Routes pass query state in
 * (`isLoading`, `isError`, `errorMessage`, `onRetry`) and compose the report
 * body + filters as children, so the route file stays thin.
 */

interface ReportPageShellProps {
  title: string;
  description?: string;
  toolbar?: ReactNode;
  loadingLabel: string;
  /** Number of skeleton sections to show while loading. */
  loadingSections?: number;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  children: ReactNode;
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
}: ReportPageShellProps) {
  if (isLoading) {
    return <ReportPageSkeleton label={loadingLabel} sections={loadingSections} />;
  }

  if (isError) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center max-w-md mx-auto">
          <p className="text-muted mb-4">{errorMessage ?? "Failed to load report."}</p>
          {onRetry && (
            <button type="button" onClick={onRetry} className="btn-secondary">
              Retry
            </button>
          )}
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
