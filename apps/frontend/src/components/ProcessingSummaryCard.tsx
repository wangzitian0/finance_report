"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Clock } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { ProcessingSummaryResponse } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/currency";
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
        <p className="text-xs text-muted uppercase tracking-wide">Processing</p>
        <p className="text-sm text-[var(--error)] mt-1">Error loading data</p>
      </div>
    );
  }

  if (!summary || summary.pending_count === 0) {
    return (
      <div className="card p-5">
        <p className="text-xs text-muted uppercase tracking-wide">Processing</p>
        <p className="text-2xl font-semibold mt-1">0</p>
        <p className="text-xs text-muted mt-1">No pending transfers</p>
      </div>
    );
  }

  return (
    <Link href="/processing" className="card p-5 hover:border-[var(--accent)] transition-colors cursor-pointer block">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs text-muted uppercase tracking-wide">Processing</p>
          <p className="text-2xl font-semibold mt-1 text-[var(--warning)]" data-testid="processing-count">
            {summary.pending_count || 0} Pending
          </p>
          <p className="text-sm font-medium mt-1">
            {formatCurrencyLocale(Number(summary.pending_total), summary.currency, "en-US", { maximumFractionDigits: 0 })}
          </p>
        </div>
        <Clock className="w-5 h-5 text-muted" />
      </div>
      {summary.oldest_pending_date && (
        <p className="text-xs text-muted mt-2">
          Oldest: {formatDateDisplay(summary.oldest_pending_date)}
        </p>
      )}
    </Link>
  );
}
