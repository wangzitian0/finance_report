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

// EPIC-022 PR6 (#864) AC22.6.2: a compact, always-honest view of the trust
// posture — how much is trusted vs. how much still needs the user.
// Enhanced for the Data Quality Observatory (#2294): when all items are verified,
// it proudly confirms audit-readiness with direct drill-down to /audit instead of vanishing.
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
        // Stay silent on network failure — the meter is non-critical chrome on Home.
        if (active) setSummary(null);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (!summary) return null;

  // When zero items need confirmation, show healthy invariant status linking to /audit
  if (summary.needsConfirmation === 0) {
    return (
      <Link
        href="/audit"
        aria-label="View data quality and invariants observatory"
        className="card block p-4 transition-colors hover:border-[var(--success)]"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="inline-flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] text-[var(--success)]">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-sm font-semibold">Financial Data Quality</h2>
              <p className="text-xs text-muted">
                All accounting invariants & balances verified
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--success)_15%,transparent)] px-2.5 py-1 text-xs font-bold text-[var(--success)]">
            Audit Ready · 100% <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        </div>
      </Link>
    );
  }

  // When confirmations or reviews are needed, show breakdown linking to /attention
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
          <h2 className="font-semibold text-sm">Data trust posture</h2>
        </div>
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)]">
          Review items <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
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
