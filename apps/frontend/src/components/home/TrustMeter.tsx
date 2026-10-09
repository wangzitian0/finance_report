"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { apiOperation } from "@/lib/api-client";
import {
  buildAttentionItems,
  summarizeTrust,
  type TrustSummary,
} from "@/lib/attention";
import type {
  BankStatementListResponse,
  ProcessingPendingListResponse,
  ReconciliationStatsResponse,
} from "@/lib/types";

// EPIC-022 PR6 (#864) AC22.6.2: a compact, always-honest view of the trust
// posture — how much is trusted vs. how much still needs the user — that makes
// the north-star (low-confidence data trending down) visible on Home. It stays
// silent when nothing needs attention.
export function TrustMeter() {
  const [summary, setSummary] = useState<TrustSummary | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [statements, stats, processing] = await Promise.all([
          apiOperation("list_statements_statements_get"),
          apiOperation("reconciliation_stats_reconciliation_stats_get"),
          apiOperation(
            "list_processing_pending_accounts_processing_pending_get",
          ),
        ]);
        if (!active) return;
        const items = buildAttentionItems({
          statements: statements?.items ?? [],
          stats: stats ?? null,
          processing: processing?.items ?? [],
        });
        setSummary(summarizeTrust(items, stats ?? null));
      } catch {
        // Stay silent on failure — the meter is non-critical chrome on Home.
        if (active) setSummary(null);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Silent when nothing needs attention (AC22.6.2).
  if (!summary || summary.needsConfirmation === 0) return null;

  return (
    <Link
      href="/attention"
      aria-label="Items that need your attention"
      className="card block p-5 transition-colors hover:border-[var(--accent)]"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="inline-flex items-center gap-2">
          <ShieldCheck
            className="h-4 w-4 text-[var(--accent)]"
            aria-hidden="true"
          />
          <h2 className="font-semibold">Data trust</h2>
        </div>
        <span className="inline-flex items-center gap-1 text-sm text-[var(--accent)]">
          Review <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 text-center">
        <Bucket label="Trusted" value={summary.trusted} tone="success" />
        <Bucket
          label="Needs your confirmation"
          value={summary.needsConfirmation}
          tone="warning"
        />
        <Bucket
          label="Low confidence"
          value={summary.lowConfidence}
          tone="error"
        />
      </div>
    </Link>
  );
}

function Bucket({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "warning" | "error";
}) {
  const color =
    tone === "success"
      ? "var(--success)"
      : tone === "warning"
        ? "var(--warning)"
        : "var(--error)";
  return (
    <div className="rounded-md bg-[var(--background-muted)] p-3">
      <p className="text-2xl font-semibold" style={{ color }}>
        {value}
      </p>
      <p className="mt-1 text-xs text-muted">{label}</p>
    </div>
  );
}
