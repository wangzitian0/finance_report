"use client";

import { RefreshCw, ShieldCheck, AlertCircle } from "lucide-react";
import { getGradeColor, getGradeLabel } from "@/hooks/useDataQualityHealth";
import type { QualityGrade } from "@/lib/types";

interface TrustScoreHeroProps {
  score: number;
  grade: QualityGrade;
  asOfDate: string;
  currency: string;
  isRefreshing?: boolean;
  onRefresh?: () => void;
}

export function TrustScoreHero({
  score,
  grade,
  asOfDate,
  currency,
  isRefreshing,
  onRefresh,
}: TrustScoreHeroProps) {
  const gradeColor = getGradeColor(grade);
  const gradeLabel = getGradeLabel(grade);

  // SVG circular gauge math
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div className="card relative overflow-hidden p-6 md:p-8">
      <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
        {/* Left Side: Score & Gauge */}
        <div className="flex items-center gap-6">
          <div className="relative flex h-28 w-28 flex-shrink-0 items-center justify-center">
            <svg
              className="h-full w-full -rotate-90 transform"
              viewBox="0 0 120 120"
              aria-hidden="true"
            >
              {/* Background ring */}
              <circle
                cx="60"
                cy="60"
                r={radius}
                className="stroke-[var(--border)]"
                strokeWidth="10"
                fill="none"
              />
              {/* Progress ring */}
              <circle
                cx="60"
                cy="60"
                r={radius}
                stroke={gradeColor}
                strokeWidth="10"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="none"
                className="transition-all duration-1000 ease-out"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-extrabold tracking-tight">
                {score}
                <span className="text-sm font-medium text-muted">%</span>
              </span>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold"
                style={{
                  backgroundColor: `color-mix(in srgb, ${gradeColor} 15%, transparent)`,
                  color: gradeColor,
                }}
              >
                {score >= 80 ? (
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {gradeLabel}
              </span>
            </div>
            <h2 className="text-xl font-bold">Data Quality & Invariant Trust</h2>
            <p className="max-w-md text-sm text-muted">
              {score >= 95
                ? "All mathematical invariants verified: Assets = Liabilities + Equity with continuous rollforward."
                : score >= 80
                  ? "Core accounting equation balanced; complete temporal timeline gaps to achieve full audit readiness."
                  : "Accounting discrepancies detected. Follow the action plan below to restore data invariants."}
            </p>
          </div>
        </div>

        {/* Right Side: Status metadata and Refresh */}
        <div className="flex flex-row items-center gap-4 text-xs text-muted md:flex-col md:items-end">
          <div>
            <span>As of: </span>
            <span className="font-medium text-[var(--foreground)]">{asOfDate}</span>
            <span className="mx-1.5">·</span>
            <span>Currency: </span>
            <span className="font-medium text-[var(--foreground)]">{currency}</span>
          </div>

          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[var(--background-muted)] disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              {isRefreshing ? "Evaluating..." : "Re-evaluate"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
