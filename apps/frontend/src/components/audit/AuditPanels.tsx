"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
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

import { Badge, EmptyState, LoadingState, type BadgeVariant } from "@/components/ui";
import { InfoHint, type GlossaryTerm } from "@/components/ui/InfoHint";
import { BackLink } from "@/components/ui/SmartBackLink";
import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useAttentionQueue } from "@/hooks/useAttentionQueue";
import { getGradeColor, getGradeLabel } from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api-client";
import { type AttentionKind } from "@/lib/attention";
import { withAttentionSource } from "@/lib/attentionNavigation";
import { getCategoriesForDirection } from "@/lib/categories";
import { summarizeReplay } from "@/lib/confidence";
import type {
  AiSuggestion,
  CorrectionLoopReplayResponse,
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
            <h2 className="text-xl font-bold">Data Quality & Book Health</h2>
            <p className="max-w-md text-sm text-muted">
              {held
                ? heldReason
                : score >= 95
                ? "All book checks verified: Assets = Liabilities + Equity with continuous monthly statements."
                : score >= 80
                  ? "Core accounting equation balanced; fill monthly statement gaps to complete audit readiness."
                  : "Accounting discrepancies detected. Follow the action plan below to fix book checks."}
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
          <p className="text-base font-bold text-[var(--success)]">All Book Checks Pass · Audit Ready</p>
          <p className="mt-0.5 text-sm text-muted">
            All accounting balance checks, monthly statement continuity, and reconciliation checks pass. No actions required.
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
                    <span className="font-semibold text-sm">{humanizeWorkflowText(item.title)}</span>
                    {/* An action that does not change the score shows no boost (#2645). */}
                    {item.score_boost > 0 && (
                      <span className="rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] px-2 py-0.5 text-[11px] font-bold text-[var(--success)]">
                        +{item.score_boost}% Trust
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted max-w-xl">{humanizeWorkflowText(item.description)}</p>
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
    { invariant: temporalInvariant, icon: History, fallbackName: "Monthly Statement Continuity", proofFormula: "Consecutive Monthly Statements (Mn+1 ≡ Mn)" },
    { invariant: reconciliationInvariant, icon: CreditCard, fallbackName: "Reconciliation & Debt Clearance", proofFormula: "Liability Settlement Check (0 Unmatched Transfers)" },
    { invariant: lineageInvariant, icon: Link2, fallbackName: "Evidence Lineage & Traceability Anchors", proofFormula: "Immutable Source Document Anchoring" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Book Checks & Balance Health</h3>
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
                    <span className="text-sm font-semibold">{humanizeWorkflowText(invariant?.name) || fallbackName}</span>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium" style={{ backgroundColor: `color-mix(in srgb, ${toneVar} 15%, transparent)`, color: toneVar }}>
                    {isHealthy ? <><CheckCircle2 className="h-3 w-3" aria-hidden="true" />Verified</> : <><AlertTriangle className="h-3 w-3" aria-hidden="true" />Attention</>}
                  </span>
                </div>
                <p className="mt-3 text-xs font-mono text-muted">{proofFormula}</p>
                <p className="mt-1 text-sm font-medium">{humanizeWorkflowText(invariant?.summary) || "Pending verification."}</p>
              </div>
              {invariant?.detail && <p className="mt-3 border-t border-[var(--border)] pt-2 text-xs text-muted">{humanizeWorkflowText(invariant.detail)}</p>}
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
          <h3 className="text-base font-semibold">Monthly Statement Timeline</h3>
          <p className="text-xs text-muted">12-month statement coverage & consecutive monthly balance continuity</p>
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

const KIND_TERM: Partial<Record<AttentionKind, GlossaryTerm>> = { statement_review: "needs_review", reconciliation_review: "match_score" };
const confidenceVariant = (c: number): BadgeVariant => (c < 40 ? "error" : c < 70 ? "warning" : "info");

/**
 * The one queue of items the user must confirm. Each row has the lowest
 * confidence first and links in one step to the statement or the entries.
 * The rows of every source that loaded show, even when another source failed.
 */
export function NeedsConfirmationQueue() {
  const { items, failed, error, retry } = useAttentionQueue();

  return (
    <section id="needs-confirmation" data-testid="needs-confirmation-queue" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">Needs Confirmation</h2>
        <p className="text-xs text-muted">The lowest-confidence items first — the few things the system could not settle on its own. Everything else is already handled automatically.</p>
      </div>
      {items === null && !error && <LoadingState label="Loading items that need confirmation" />}
      {error && <EmptyState role="alert" title="Couldn't load the items that need confirmation" description={error} action={<button onClick={retry} className="btn-secondary text-sm">Retry</button>} />}
      {items !== null && !failed && items.length === 0 && <EmptyState title="All clear" description="Nothing needs your review right now — the system trusts the rest of your data." />}
      {items !== null && items.length > 0 && (
        <>
          <div className="card divide-y divide-[var(--border)]">
            {items.map((item) => (
              <Link key={item.id} href={withAttentionSource(item.href)} className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-[var(--background-muted)]/50">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium line-clamp-2 break-words">{item.title}</span>
                    {KIND_TERM[item.kind] && <InfoHint term={KIND_TERM[item.kind] as GlossaryTerm} label={item.detail} />}
                  </div>
                  <p className="text-xs text-muted mt-0.5">{item.detail}</p>
                  <p className="text-xs text-muted mt-1 max-w-prose">{item.reason}</p>
                </div>
                <div className="flex flex-shrink-0 items-center gap-3">
                  <Badge variant={confidenceVariant(item.confidence)}>{item.confidence}% confidence</Badge>
                  <ArrowRight className="h-4 w-4 text-muted" aria-hidden="true" />
                </div>
              </Link>
            ))}
          </div>
          <p className="inline-flex items-center gap-1.5 text-xs text-muted">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            Sorted by confidence — clearing these drives your low-confidence data down.
          </p>
        </>
      )}
    </section>
  );
}

type FeedbackAction = "accept" | "reject" | "edit_accept";

const EFFECT_LABEL: Record<string, string> = {
  accepted: "Accepted. The one-click approval of the statement posts it.",
  rejected: "Rejected. The approval uses the default category.",
  corrected: "Corrected. The one-click approval posts your category.",
  recorded: "Feedback saved. It did not change the suggestion.",
};

/**
 * The pending AI suggestions, optionally of one statement. The `/audit` tab label counts them
 * and the queue lists them through this one cache entry. Each mount reads the list again: a
 * decision does not remove a suggestion from the cached list.
 */
export function useAiSuggestions(statementId?: string) {
  return useApiQuery(
    ["ai", "suggestions", statementId ?? null],
    "list_ai_suggestions_ai_suggestions_get",
    statementId ? { query: { statement_id: statementId } } : {},
    { staleTime: 0 },
  );
}

/** Pending AI suggestions that the user accepts, rejects or corrects. */
export function AiSuggestionsQueue() {
  const searchParams = useSearchParams();
  const statementId = searchParams?.get("statement_id")?.trim() || undefined;
  const returnTo = searchParams?.get("return_to")?.trim() || undefined;
  const suggestionsQuery = useAiSuggestions(statementId);
  const suggestions: AiSuggestion[] = suggestionsQuery.data?.items ?? [];
  const loading = suggestionsQuery.isPending;
  const error = suggestionsQuery.isError ? suggestionsQuery.error.message || "Failed to load AI suggestions" : null;
  const [correctedValues, setCorrectedValues] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  const submitFeedback = async (suggestion: AiSuggestion, action: FeedbackAction) => {
    const id = suggestion.suggestion_id;
    const corrected = correctedValues[id]?.trim();
    setSaving((c) => ({ ...c, [id]: true }));
    try {
      const saved = await apiOperation("create_ai_feedback_ai_feedback_post", {
        body: { suggestion_id: id, action, ...(action === "edit_accept" && corrected ? { corrected_value: { value: corrected } } : {}) },
      });
      setRowErrors(({ [id]: _cleared, ...rest }) => rest);
      setDecisions((c) => ({ ...c, [id]: EFFECT_LABEL[saved?.effect ?? "recorded"] ?? EFFECT_LABEL.recorded }));
    } catch (err) {
      setRowErrors((c) => ({ ...c, [id]: err instanceof Error ? err.message : "Failed to save your decision" }));
    } finally {
      setSaving(({ [id]: _done, ...rest }) => rest);
    }
  };

  const renderCorrectionInput = (suggestion: AiSuggestion, surface: "mobile" | "table") => {
    const inputId = `corrected-${surface}-${suggestion.suggestion_id}`;
    const options = getCategoriesForDirection(suggestion.direction);
    return (
      <>
        <label className="sr-only" htmlFor={inputId}>Corrected value</label>
        <select
          id={inputId}
          aria-label="Corrected value"
          className="input py-2 text-sm"
          value={correctedValues[suggestion.suggestion_id] ?? ""}
          onChange={(e) => setCorrectedValues((c) => ({ ...c, [suggestion.suggestion_id]: e.target.value }))}
        >
          <option value="">Select category...</option>
          {options.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
        </select>
      </>
    );
  };

  const renderActionButtons = (suggestion: AiSuggestion, className = "") => (
    <div className={`grid grid-cols-2 gap-2 sm:flex sm:justify-end ${className}`}>
      <button type="button" className="btn-primary text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "accept")}>Accept</button>
      <button type="button" className="btn-secondary text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "reject")}>Reject</button>
      <button type="button" className="btn-secondary col-span-2 text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "edit_accept")}>Edit-then-Accept</button>
    </div>
  );

  const renderOutcome = (suggestion: AiSuggestion) => (
    <div className="mt-1 min-h-[1rem] text-xs sm:text-right">
      <p role="status" aria-live="polite" className="text-muted">{saving[suggestion.suggestion_id] ? "Saving..." : (decisions[suggestion.suggestion_id] ?? "")}</p>
      {rowErrors[suggestion.suggestion_id] && <p role="alert" className="text-[var(--error)]">{rowErrors[suggestion.suggestion_id]}</p>}
    </div>
  );

  if (loading) {
    return <section id="ai-suggestions"><div className="card p-6 text-center text-muted md:p-8">Loading AI suggestions...</div></section>;
  }

  return (
    <section id="ai-suggestions" className="space-y-3">
      {returnTo && <div><BackLink href="/audit">Back</BackLink></div>}
      <div>
        <h2 className="text-sm font-semibold">Suggestions to review</h2>
        <p className="text-xs text-muted">Approve or correct the AI&apos;s suggested categories and matches that need a human eye.</p>
      </div>
      {error && <div className="alert-error">{error}</div>}
      <div className="card overflow-hidden">
        {suggestions.length === 0 ? (
          <div className="p-8 text-center text-muted">No pending AI suggestions</div>
        ) : (
          <>
            <div data-testid="ai-suggestions-mobile-list" className="divide-y divide-[var(--border)] md:hidden">
              {suggestions.map((suggestion) => (
                <article key={suggestion.suggestion_id} data-testid={`ai-suggestion-mobile-card-${suggestion.suggestion_id}`} className="space-y-4 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><p className="text-xs font-medium uppercase text-muted">Transaction</p><p className="mt-1 break-words font-medium">{suggestion.transaction}</p></div>
                    <div className="flex-shrink-0 rounded-md bg-[var(--warning-muted)] px-2.5 py-1 text-sm font-semibold text-[var(--warning)]">{suggestion.ai_score}</div>
                  </div>
                  <div className="grid grid-cols-1 gap-3 text-sm">
                    <div><p className="text-xs font-medium uppercase text-muted">Suggestion</p><p className="mt-1 break-words">{suggestion.suggested_category_or_match}</p></div>
                    <div><p className="text-xs font-medium uppercase text-muted">Reasoning</p><p className="mt-1 break-words text-muted">{suggestion.ai_reasoning}</p></div>
                  </div>
                  <div className="space-y-3">{renderCorrectionInput(suggestion, "mobile")}{renderActionButtons(suggestion)}{renderOutcome(suggestion)}</div>
                </article>
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-[var(--background-muted)]/50 border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left px-4 py-3">Transaction</th>
                    <th className="text-left px-4 py-3">Suggestion</th>
                    <th className="text-left px-4 py-3">AI Score</th>
                    <th className="text-left px-4 py-3">AI Reasoning</th>
                    <th className="text-left px-4 py-3">Corrected value</th>
                    <th className="text-right px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {suggestions.map((suggestion) => (
                    <tr key={suggestion.suggestion_id}>
                      <td className="px-4 py-3 font-medium">{suggestion.transaction}</td>
                      <td className="px-4 py-3">{suggestion.suggested_category_or_match}</td>
                      <td className="px-4 py-3 text-[var(--warning)] font-semibold">{suggestion.ai_score}</td>
                      <td className="px-4 py-3 text-muted">{suggestion.ai_reasoning}</td>
                      <td className="px-4 py-3 min-w-[220px]">{renderCorrectionInput(suggestion, "table")}</td>
                      <td className="px-4 py-3 min-w-[240px]">{renderActionButtons(suggestion)}{renderOutcome(suggestion)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

/** Shows how past confirmations reduce extraction errors on new statements. */
export function CorrectionLoopProof() {
  const [replay, setReplay] = useState<CorrectionLoopReplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setReplay(null);
    setError(null);
    void (async () => {
      try {
        const result = await apiOperation("get_correction_loop_replay_metrics_correction_loop_replay_get");
        if (active) setReplay(result);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load correction-loop proof");
      }
    })();
    return () => { active = false; };
  }, [attempt]);

  const summary = replay ? summarizeReplay(replay) : null;

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">Correction Loop Proof</h2>
        <p className="text-xs text-muted">See how your past reviews improve automatic statement reading.</p>
      </div>
      {replay === null && !error && <LoadingState label="Loading correction-loop proof" />}
      {error && <EmptyState role="alert" title="Couldn't load correction-loop proof" description={error} action={<button onClick={() => setAttempt((v) => v + 1)} className="btn-secondary text-sm">Retry</button>} />}
      {summary && !error && (
        <section className="card p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">Accuracy on Past Edits</h3>
            {summary.hasHoldout && <Badge variant={summary.reduced ? "success" : "muted"}>{summary.reduced ? "Improves extraction" : "No measurable improvement"}</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted">Shows how past review corrections reduce extraction errors on new statements.</p>
          {summary.hasHoldout ? (
            <div className="mt-4 grid grid-cols-1 gap-3 text-center sm:grid-cols-2">
              <div className="rounded-md bg-[var(--background-muted)] p-3"><p className="text-2xl font-semibold tabular-nums">{summary.before}</p><p className="mt-1 text-xs text-muted">Before correction reuse</p></div>
              <div className="rounded-md bg-[var(--background-muted)] p-3"><p className="text-2xl font-semibold tabular-nums">{summary.after}</p><p className="mt-1 text-xs text-muted">After correction reuse</p></div>
            </div>
          ) : (
            <EmptyState framed={false} className="mt-4" title="Not enough correction history yet" description="An accuracy check appears after enough recurring corrections exist." />
          )}
        </section>
      )}
    </div>
  );
}
