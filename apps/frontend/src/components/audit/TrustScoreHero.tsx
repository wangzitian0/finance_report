"use client";

import Link from "next/link";
import {
  AlertCircle,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Clock,
  CreditCard,
  FileText,
  GitMerge,
  History,
  Link2,
  RefreshCw,
  Scale,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { getGradeColor, getGradeLabel } from "@/hooks/useDataQualityHealth";
import type {
  InvariantStatus,
  MonthContinuityBucket,
  QualityActionItem,
  QualityGrade,
} from "@/lib/types";

interface TrustScoreHeroProps {
  score: number;
  grade: QualityGrade;
  asOfDate: string;
  currency: string;
  isRefreshing?: boolean;
  onRefresh?: () => void;
  /**
   * Why the books are not ready yet: a blocker or an unmatched row (#2646). While it is set, the
   * hero shows no audit-ready grade: the score checks the invariants, not the open items.
   */
  heldReason?: string | null;
}

/** The grade label, or the hold label while an open item holds the audit-ready grade. */
export function heldGradeLabel(grade: QualityGrade, heldReason?: string | null): string {
  return heldReason && grade === "A_AUDIT_READY" ? "Open items remain" : getGradeLabel(grade);
}

export function TrustScoreHero({ score, grade, asOfDate, currency, isRefreshing, onRefresh, heldReason }: TrustScoreHeroProps) {
  const held = Boolean(heldReason) && grade === "A_AUDIT_READY";
  const gradeColor = held ? "var(--warning)" : getGradeColor(grade);
  const gradeLabel = heldGradeLabel(grade, heldReason);
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div className="card relative overflow-hidden p-6 md:p-8">
      <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
        <div className="flex items-center gap-6">
          <div className="relative flex h-28 w-28 flex-shrink-0 items-center justify-center">
            <svg className="h-full w-full -rotate-90 transform" viewBox="0 0 120 120" aria-hidden="true">
              <circle cx="60" cy="60" r={radius} className="stroke-[var(--border)]" strokeWidth="10" fill="none" />
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
                style={{ backgroundColor: `color-mix(in srgb, ${gradeColor} 15%, transparent)`, color: gradeColor }}
              >
                {score >= 80 ? <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" /> : <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />}
                {gradeLabel}
              </span>
            </div>
            <h2 className="text-xl font-bold">Data Quality & Invariant Trust</h2>
            <p className="max-w-md text-sm text-muted">
              {held
                ? heldReason
                : score >= 95
                ? "All mathematical invariants verified: Assets = Liabilities + Equity with continuous rollforward."
                : score >= 80
                  ? "Core accounting equation balanced; complete temporal timeline gaps to achieve full audit readiness."
                  : "Accounting discrepancies detected. Follow the action plan below to restore data invariants."}
            </p>
          </div>
        </div>

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
              <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} aria-hidden="true" />
              {isRefreshing ? "Evaluating..." : "Re-evaluate"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ActionChecklist({
  actionItems,
  heldReason,
}: {
  actionItems: QualityActionItem[];
  /** See `TrustScoreHero`. While it is set, an empty checklist states the open items, not audit readiness. */
  heldReason?: string | null;
}) {
  const items = actionItems ?? [];

  if (items.length === 0 && heldReason) {
    return (
      <div className="card flex items-center gap-4 border-[var(--warning)] p-6">
        <span className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-[var(--warning)] text-white">
          <AlertTriangle className="h-6 w-6" aria-hidden="true" />
        </span>
        <div>
          <p className="text-base font-bold">The checks pass. Open items remain.</p>
          <p className="mt-0.5 text-sm text-muted">{heldReason}</p>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="card flex items-center gap-4 border-[var(--success)] bg-[color-mix(in_srgb,var(--success)_8%,transparent)] p-6">
        <span className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-[var(--success)] text-white">
          <CheckCircle2 className="h-6 w-6" aria-hidden="true" />
        </span>
        <div>
          <p className="text-base font-bold text-[var(--success)]">100% Invariant Perfection · Audit Ready</p>
          <p className="mt-0.5 text-sm text-muted">
            All accounting balance proofs, temporal rollforward continuity, and reconciliation purity checks are fully satisfied. No remedial actions required.
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
          <p className="text-xs text-muted">Complete prioritized actions to systematically increase your data trust score</p>
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
          const toneVar = isP0 ? "var(--error)" : isP1 ? "var(--warning)" : "var(--accent)";

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
                  className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: `color-mix(in srgb, ${toneVar} 15%, transparent)`, color: toneVar }}
                >
                  <ActionIcon className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-block rounded px-2 py-0.5 text-[11px] font-semibold ${isP0 ? "bg-[var(--error)] text-white" : isP1 ? "bg-[var(--warning)] text-white" : "bg-[var(--background-muted)] text-muted"}`}>
                      {item.priority}
                    </span>
                    <span className="font-semibold text-sm">{item.title}</span>
                    {/* An action that does not change the score shows no boost (#2645). */}
                    {item.score_boost > 0 && (
                      <span className="rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] px-2 py-0.5 text-[11px] font-bold text-[var(--success)]">
                        +{item.score_boost}% Trust
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted max-w-xl">{item.description}</p>
                </div>
              </div>

              <Link href={item.action_url} className="btn-primary inline-flex flex-shrink-0 items-center gap-1.5 self-end px-3.5 py-1.5 text-xs sm:self-center">
                Resolve <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function InvariantChecksGrid({
  equationInvariant,
  temporalInvariant,
  reconciliationInvariant,
  lineageInvariant,
}: {
  equationInvariant: InvariantStatus;
  temporalInvariant: InvariantStatus;
  reconciliationInvariant: InvariantStatus;
  lineageInvariant: InvariantStatus;
}) {
  const cards = [
    { invariant: equationInvariant, icon: Scale, fallbackName: "Accounting Equation Balance", proofFormula: "Assets = Liabilities + Equity (Δ = 0.00)" },
    { invariant: temporalInvariant, icon: History, fallbackName: "Temporal Continuity & Rollforward", proofFormula: "Consecutive Monthly Statements (Mn+1 ≡ Mn)" },
    { invariant: reconciliationInvariant, icon: CreditCard, fallbackName: "Reconciliation & Debt Clearance Purity", proofFormula: "Liability Settlement Purity (0 P&L Leakage)" },
    { invariant: lineageInvariant, icon: Link2, fallbackName: "Evidence Lineage & Traceability Anchors", proofFormula: "Immutable Source Document Anchoring" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Invariant Proofs & Mathematical Health</h3>
        <span className="text-xs text-muted">Continuous real-time verification</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {cards.map(({ invariant, icon: Icon, fallbackName, proofFormula }) => {
          const isHealthy = Boolean(invariant?.is_healthy);
          const toneVar = isHealthy ? "var(--success)" : "var(--warning)";
          return (
            <div
              key={fallbackName}
              className={`card flex flex-col justify-between p-5 transition-colors ${
                isHealthy ? "border-[var(--border)] hover:border-[var(--success)]" : "border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_4%,transparent)]"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ backgroundColor: `color-mix(in srgb, ${toneVar} 15%, transparent)`, color: toneVar }}>
                      <Icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="text-sm font-semibold">{invariant?.name || fallbackName}</span>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium" style={{ backgroundColor: `color-mix(in srgb, ${toneVar} 15%, transparent)`, color: toneVar }}>
                    {isHealthy ? <><CheckCircle2 className="h-3 w-3" aria-hidden="true" />Verified</> : <><AlertTriangle className="h-3 w-3" aria-hidden="true" />Attention</>}
                  </span>
                </div>
                <p className="mt-3 text-xs font-mono text-muted">{proofFormula}</p>
                <p className="mt-1 text-sm font-medium">{invariant?.summary ?? "Pending verification."}</p>
              </div>
              {invariant?.detail && <p className="mt-3 border-t border-[var(--border)] pt-2 text-xs text-muted">{invariant.detail}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TemporalTimelineGrid({ timeline }: { timeline: MonthContinuityBucket[] }) {
  const buckets = timeline ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-center">
        <div>
          <h3 className="text-base font-semibold">Temporal Continuity Timeline</h3>
          <p className="text-xs text-muted">12-month statement coverage & consecutive cash rollforward continuity</p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--success)]" /> Continuous</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--warning)]" /> Missing Month</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--accent)]" /> Processing</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--border)]" /> No Data</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {buckets.map((bucket) => {
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
                    <span title="Continuous verified statement" className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]">
                      <Check className="h-3 w-3" />
                    </span>
                  )}
                  {isGap && (
                    <span title="Missing statement gap detected" className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--warning)_15%,transparent)] text-[var(--warning)]">
                      <AlertCircle className="h-3 w-3" />
                    </span>
                  )}
                  {isPending && (
                    <span title="Statement currently processing" className="flex h-5 w-5 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]">
                      <Clock className="h-3 w-3 animate-spin" />
                    </span>
                  )}
                </div>
                <div className="mt-2 text-[11px] text-muted">
                  {bucket.statement_count > 0 ? (
                    <span>{bucket.statement_count} statement{bucket.statement_count > 1 ? "s" : ""}</span>
                  ) : isGap ? (
                    <span className="font-medium text-[var(--warning)]">Missing Period</span>
                  ) : (
                    <span>No statements</span>
                  )}
                </div>
              </div>
              <div className="mt-3 border-t border-[var(--border)] pt-2 text-[11px]">
                {isGap ? (
                  <Link href={`/upload?month=${bucket.month}`} className="inline-flex items-center gap-1 font-medium text-[var(--warning)] hover:underline">
                    <Upload className="h-3 w-3" /> Upload
                  </Link>
                ) : isPending ? (
                  <Link href="/upload" className="inline-flex items-center gap-1 font-medium text-[var(--accent)] hover:underline">
                    Review <ArrowUpRight className="h-3 w-3" />
                  </Link>
                ) : bucket.net_movement !== null && bucket.net_movement !== undefined ? (
                  <span className="font-mono text-muted">Net: {Number(bucket.net_movement) >= 0 ? "+" : ""}{bucket.net_movement}</span>
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
