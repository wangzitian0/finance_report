"use client";

import Link from "next/link";
import { CheckCircle2, ArrowRight, Upload, FileText, GitMerge, AlertOctagon } from "lucide-react";
import type { QualityActionItem } from "@/lib/types";

interface ActionChecklistProps {
  actionItems: QualityActionItem[];
}

export function ActionChecklist({ actionItems }: ActionChecklistProps) {
  const items = actionItems ?? [];

  if (items.length === 0) {
    return (
      <div className="card flex items-center gap-4 border-[var(--success)] bg-[color-mix(in_srgb,var(--success)_8%,transparent)] p-6">
        <span className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-[var(--success)] text-white">
          <CheckCircle2 className="h-6 w-6" aria-hidden="true" />
        </span>
        <div>
          <p className="text-base font-bold text-[var(--success)]">
            100% Invariant Perfection · Audit Ready
          </p>
          <p className="mt-0.5 text-sm text-muted">
            All accounting balance proofs, temporal rollforward continuity, and reconciliation purity
            checks are fully satisfied. No remedial actions required.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Ordered Quality Boost Actions</h3>
          <p className="text-xs text-muted">
            Complete prioritized actions to systematically increase your data trust score
          </p>
        </div>
        <span className="rounded-full bg-[var(--background-muted)] px-2.5 py-0.5 text-xs font-medium text-muted">
          {items.length} action{items.length > 1 ? "s" : ""} pending
        </span>
      </div>

      <div className="grid gap-3">
        {items.map((item) => {
          const isP0 = item.priority === "P0";
          const isP1 = item.priority === "P1";

          const ActionIcon =
            item.action_type === "UPLOAD_STATEMENT"
              ? Upload
              : item.action_type === "REVIEW_STATEMENT"
                ? FileText
                : item.action_type === "RECONCILE_TRANSACTIONS"
                  ? GitMerge
                  : AlertOctagon;

          return (
            <div
              key={item.id}
              className={`card flex flex-col items-start justify-between gap-4 p-4 transition-colors sm:flex-row sm:items-center ${
                isP0
                  ? "border-[var(--error)] bg-[color-mix(in_srgb,var(--error)_4%,transparent)]"
                  : isP1
                    ? "border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_4%,transparent)]"
                    : "border-[var(--border)] hover:border-[var(--accent)]"
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className={`mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg ${
                    isP0
                      ? "bg-[color-mix(in_srgb,var(--error)_15%,transparent)] text-[var(--error)]"
                      : isP1
                        ? "bg-[color-mix(in_srgb,var(--warning)_15%,transparent)] text-[var(--warning)]"
                        : "bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]"
                  }`}
                >
                  <ActionIcon className="h-5 w-5" aria-hidden="true" />
                </span>

                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-[11px] font-semibold ${
                        isP0
                          ? "bg-[var(--error)] text-white"
                          : isP1
                            ? "bg-[var(--warning)] text-white"
                            : "bg-[var(--background-muted)] text-muted"
                      }`}
                    >
                      {item.priority}
                    </span>
                    <span className="font-semibold text-sm">{item.title}</span>
                    <span className="rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] px-2 py-0.5 text-[11px] font-bold text-[var(--success)]">
                      +{item.score_boost}% Trust
                    </span>
                  </div>
                  <p className="text-xs text-muted max-w-xl">{item.description}</p>
                </div>
              </div>

              <Link
                href={item.action_url}
                className="btn-primary inline-flex flex-shrink-0 items-center gap-1.5 self-end px-3.5 py-1.5 text-xs sm:self-center"
              >
                Resolve
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          );
        })}
      </div>
    </div>
  );
}
