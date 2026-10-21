"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ChevronRight, Layers } from "lucide-react";

import {
  ActionChecklist,
  InvariantChecksGrid,
  TemporalTimelineGrid,
  TrustScoreHero,
} from "@/components/audit/TrustScoreHero";
import { auditHubItems } from "@/components/navigation";
import { Badge, PageHeader } from "@/components/ui";
import { useDataQualityHealth } from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api-client";
import { buildAttentionItems, type AttentionItem } from "@/lib/attention";
import { withAttentionSource } from "@/lib/attentionNavigation";

const DESCRIPTIONS: Record<string, string> = {
  "/confidence": "How trusted each number is — confirmations needed and low-confidence items.",
  "/reconciliation": "How well your statements reconcile, and anything still unmatched.",
  "/journal": "The double-entry ledger behind every figure in your reports.",
  "/upload": "Uploaded bank, brokerage, and card statements with extraction status.",
  "/processing": "In-flight transfer holdings awaiting paired institution statements.",
};

export default function AuditPage() {
  const { data, isLoading, isError, refetch, isFetching } = useDataQualityHealth();
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);

  useEffect(() => {
    if (!data) return;
    let active = true;
    Promise.all([
      Promise.resolve(apiOperation("list_statements_statements_get")).catch(() => null),
      Promise.resolve(apiOperation("reconciliation_stats_reconciliation_stats_get")).catch(() => null),
      Promise.resolve(apiOperation("list_processing_pending_accounts_processing_pending_get")).catch(() => null),
    ]).then(([statements, stats, processing]) => {
      if (!active) return;
      if (!statements && !stats && !processing) return;
      setAttentionItems(
        buildAttentionItems({
          statements: statements?.items ?? [],
          stats: stats ?? null,
          processing: processing?.items ?? [],
        }),
      );
    });
    return () => {
      active = false;
    };
  }, [data]);

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
      ) : isError || !data || typeof data.score !== "number" || !data.equation_invariant ? (
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
          <TrustScoreHero
            score={data.score}
            grade={data.grade}
            asOfDate={data.as_of_date}
            currency={data.currency}
            isRefreshing={isFetching}
            onRefresh={() => refetch()}
          />

          <ActionChecklist actionItems={data.action_items} />

          <InvariantChecksGrid
            equationInvariant={data.equation_invariant}
            temporalInvariant={data.temporal_continuity_invariant}
            reconciliationInvariant={data.reconciliation_purity_invariant}
            lineageInvariant={data.lineage_anchors_invariant}
          />

          <TemporalTimelineGrid timeline={data.timeline} />
        </>
      )}

      <div className="border-t border-[var(--border)] pt-6">
        <div
          data-testid="audit-needs-confirmation-bar"
          className="card mb-6 space-y-3 p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold">Needs Confirmation</h2>
              <p className="text-xs text-muted">
                Confirm items that need your input so your financial reports stay accurate.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href="/attention" className="btn-secondary text-xs">
                Low-confidence items
              </Link>
              <Link href="/reconciliation/unmatched" className="btn-secondary text-xs">
                Unmatched bank lines
              </Link>
              <Link href="/upload" className="btn-secondary text-xs">
                Uploaded statements
              </Link>
            </div>
          </div>

          {attentionItems.length > 0 && (
            <div className="divide-y divide-[var(--border)] border-t border-[var(--border)] pt-2">
              {attentionItems.slice(0, 5).map((item) => (
                <Link
                  key={item.id}
                  href={withAttentionSource(item.href)}
                  className="flex items-center justify-between gap-3 py-2.5 text-xs transition-colors hover:text-[var(--accent)]"
                >
                  <div className="min-w-0">
                    <span className="font-medium">{item.title}</span>
                    <span className="ml-2 text-muted">{item.detail}</span>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <Badge variant={item.confidence < 40 ? "error" : item.confidence < 70 ? "warning" : "info"}>
                      {item.confidence}% confidence
                    </Badge>
                    <ArrowRight className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

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
