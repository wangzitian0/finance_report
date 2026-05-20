"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { ProcessingSummaryResponse } from "@/lib/types";
import { formatCurrency, isAmountZero } from "@/lib/currency";
import { formatDateDisplay } from "@/lib/date";

export default function ProcessingSummaryCard() {
  const [summary, setSummary] = useState<ProcessingSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSummary() {
      try {
        const data = await apiFetch<ProcessingSummaryResponse>("/api/accounts/processing/summary");
        setSummary(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load summary");
      } finally {
        setLoading(false);
      }
    }
    fetchSummary();
  }, []);

  if (loading) {
    return (
      <div className="card p-5 animate-pulse">
        <div className="h-4 bg-[var(--background-muted)] rounded w-24 mb-2" />
        <div className="h-8 bg-[var(--background-muted)] rounded w-32 mb-2" />
        <div className="h-4 bg-[var(--background-muted)] rounded w-20" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-5 border-[var(--error)]/30">
        <p className="text-xs text-muted uppercase">Processing</p>
        <p className="text-sm text-[var(--error)] mt-1">Error loading data</p>
      </div>
    );
  }

  const pendingCount = summary?.pending_count ?? 0;
  const currentBalance = summary?.current_balance ?? summary?.pending_total ?? "0.00";
  const currency = summary?.currency ?? "SGD";
  const hasUnresolvedBalance = !isAmountZero(currentBalance, 0);

  return (
    <Link href="/processing" className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs text-muted uppercase">Processing</p>
          <p
            className={`text-2xl font-semibold mt-1 ${hasUnresolvedBalance ? "text-[var(--warning)]" : ""}`}
            data-testid="processing-balance"
          >
            {formatCurrency(currentBalance, currency)}
          </p>
          <p className="text-sm font-medium mt-1" data-testid="processing-count">
            {pendingCount} Pending
          </p>
        </div>
        {hasUnresolvedBalance ? (
          <AlertTriangle
            className="w-5 h-5 text-[var(--warning)]"
            aria-label="Unresolved Processing Account balance"
          />
        ) : (
          <Clock className="w-5 h-5 text-muted" aria-hidden="true" />
        )}
      </div>
      {hasUnresolvedBalance ? (
        <p className="text-xs text-[var(--warning)] mt-2">Unresolved in-transit balance</p>
      ) : (
        <p className="text-xs text-muted mt-2">Balanced</p>
      )}
      {summary?.oldest_pending_date && (
        <p className="text-xs text-muted mt-2">
          Oldest: {formatDateDisplay(summary.oldest_pending_date)}
        </p>
      )}
    </Link>
  );
}
