"use client";

import Link from "next/link";
import { ChevronRight, Layers } from "lucide-react";

import { ActionChecklist } from "@/components/audit/ActionChecklist";
import { InvariantChecksGrid } from "@/components/audit/InvariantChecksGrid";
import { TemporalTimelineGrid } from "@/components/audit/TemporalTimelineGrid";
import { TrustScoreHero } from "@/components/audit/TrustScoreHero";
import { auditHubItems } from "@/components/navigation";
import { PageHeader } from "@/components/ui";
import { useDataQualityHealth } from "@/hooks/useDataQualityHealth";

const DESCRIPTIONS: Record<string, string> = {
  "/confidence": "How trusted each number is — confirmations needed and low-confidence items.",
  "/reconciliation": "How well your statements reconcile, and anything still unmatched.",
  "/journal": "The double-entry ledger behind every figure in your reports.",
  "/processing": "The status of statements still being parsed or transformed.",
};

export default function AuditPage() {
  const { data, isLoading, isError, refetch, isFetching } = useDataQualityHealth();

  return (
    <div className="space-y-8 p-6 max-w-7xl mx-auto">
      <PageHeader
        title="Audit"
        description="Financial Data Quality & Audit Observatory. Continuous mathematical verification of accounting invariants, statement rollforward continuity, and audit-ready integrity."
      />

      {isLoading ? (
        <div className="card space-y-4 p-8 text-center">
          <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--accent)]" />
          <p className="text-sm text-muted">Evaluating accounting invariants and temporal timeline...</p>
        </div>
      ) : isError || !data ? (
        <div className="card border-[var(--error)] p-6 text-center">
          <p className="text-sm font-medium text-[var(--error)]">
            Failed to evaluate data quality health.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="btn-primary mt-3 text-xs"
          >
            Retry Evaluation
          </button>
        </div>
      ) : (
        <>
          {/* 1. Score Hero */}
          <TrustScoreHero
            score={data.score}
            grade={data.grade}
            asOfDate={data.as_of_date}
            currency={data.currency}
            isRefreshing={isFetching}
            onRefresh={() => refetch()}
          />

          {/* 2. Prioritized Action Checklist */}
          <ActionChecklist actionItems={data.action_items} />

          {/* 3. Invariant Proofs */}
          <InvariantChecksGrid
            equationInvariant={data.equation_invariant}
            temporalInvariant={data.temporal_continuity_invariant}
            reconciliationInvariant={data.reconciliation_purity_invariant}
            lineageInvariant={data.lineage_anchors_invariant}
          />

          {/* 4. Temporal Rollforward Timeline */}
          <TemporalTimelineGrid timeline={data.timeline} />
        </>
      )}

      {/* 5. Underlying Accounting Machinery & Deep Links */}
      <div className="border-t border-[var(--border)] pt-6">
        <div className="mb-3 flex items-center gap-2">
          <Layers className="h-4 w-4 text-muted" aria-hidden="true" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">
            Accounting Machinery & Ledgers
          </h3>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {auditHubItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="card flex items-start gap-3 p-4 transition-colors hover:bg-[var(--background-muted)]"
              >
                <span className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-[var(--accent-muted)] text-[var(--accent)]">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm">{item.label}</span>
                    <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted" aria-hidden="true" />
                  </span>
                  <span className="mt-0.5 block text-xs text-muted">
                    {DESCRIPTIONS[item.href]}
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
