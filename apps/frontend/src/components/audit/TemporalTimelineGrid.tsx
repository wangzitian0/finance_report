"use client";

import Link from "next/link";
import { Check, AlertCircle, Clock, Upload, ArrowUpRight } from "lucide-react";
import type { MonthContinuityBucket } from "@/lib/types";

interface TemporalTimelineGridProps {
  timeline: MonthContinuityBucket[];
}

export function TemporalTimelineGrid({ timeline }: TemporalTimelineGridProps) {
  return (
    <div className="space-y-3">
      <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
        <div>
          <h3 className="text-base font-semibold">Temporal Continuity Timeline</h3>
          <p className="text-xs text-muted">
            12-month statement coverage & consecutive cash rollforward continuity
          </p>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--success)]" /> Continuous
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--warning)]" /> Missing Month
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--accent)]" /> Processing
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--border)]" /> No Data
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {timeline.map((bucket) => {
          const isGap = bucket.status === "GAP_DETECTED";
          const isHealthy = bucket.status === "HEALTHY";
          const isPending = bucket.status === "PENDING_PROCESSING";

          return (
            <div
              key={bucket.month}
              className={`card flex flex-col justify-between p-3.5 transition-colors ${
                isGap
                  ? "border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_5%,transparent)]"
                  : isHealthy
                    ? "border-[var(--border)] hover:border-[var(--success)]"
                    : isPending
                      ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_5%,transparent)]"
                      : "opacity-60"
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-semibold">{bucket.month}</span>
                  {isHealthy && (
                    <span
                      title="Continuous verified statement"
                      className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]"
                    >
                      <Check className="h-3 w-3" />
                    </span>
                  )}
                  {isGap && (
                    <span
                      title="Missing statement gap detected"
                      className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--warning)_15%,transparent)] text-[var(--warning)]"
                    >
                      <AlertCircle className="h-3 w-3" />
                    </span>
                  )}
                  {isPending && (
                    <span
                      title="Statement currently processing"
                      className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]"
                    >
                      <Clock className="h-3 w-3 animate-spin" />
                    </span>
                  )}
                </div>

                <div className="mt-2 text-[11px] text-muted">
                  {bucket.statement_count > 0 ? (
                    <span>
                      {bucket.statement_count} statement
                      {bucket.statement_count > 1 ? "s" : ""}
                    </span>
                  ) : isGap ? (
                    <span className="font-medium text-[var(--warning)]">Missing Period</span>
                  ) : (
                    <span>No statements</span>
                  )}
                </div>
              </div>

              <div className="mt-3 border-t border-[var(--border)] pt-2 text-[11px]">
                {isGap ? (
                  <Link
                    href={`/upload?month=${bucket.month}`}
                    className="inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline"
                  >
                    <Upload className="h-3 w-3" />
                    Upload
                  </Link>
                ) : isPending ? (
                  <Link
                    href="/processing"
                    className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline"
                  >
                    Review <ArrowUpRight className="h-3 w-3" />
                  </Link>
                ) : bucket.net_movement !== null && bucket.net_movement !== undefined ? (
                  <span className="font-mono text-muted">
                    Net: {Number(bucket.net_movement) >= 0 ? "+" : ""}
                    {bucket.net_movement}
                  </span>
                ) : (
                  <span className="text-muted">—</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
