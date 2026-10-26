"use client";

import { AlertTriangle } from "lucide-react";

import { Alert } from "@/components/ui";
import { useApiQuery } from "@/hooks/useApiQuery";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatDateDisplay } from "@/lib/date";
import { PROCESSING_PENDING_QUERY_KEY, SHARED_STALE_MS } from "@/lib/sharedQueries";

const OVERDUE_DAYS = 7;

/**
 * Money that left one account but has not yet arrived in the other account's statement.
 * The card shows nothing when no transfer is waiting.
 */
export function ProcessingTransfers() {
  const pending = useApiQuery(
    PROCESSING_PENDING_QUERY_KEY,
    "list_processing_pending_accounts_processing_pending_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );

  if (pending.isError) return <Alert variant="error" className="mb-6">{pending.error?.message ?? "Failed to load pending transfers"}</Alert>;
  const items = pending.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section id="transfers" aria-label="Transfers in flight" className="card mb-6 overflow-hidden">
      <div className="card-header flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Transfers in flight</h3>
        <span className="text-xs text-muted">Waiting for the matching statement · {items.length} total</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--background-muted)] border-b border-[var(--border)]">
            <tr>
              <th className="px-6 py-3 font-semibold">Started</th>
              <th className="px-6 py-3 font-semibold">From</th>
              <th className="px-6 py-3 font-semibold">To</th>
              <th className="px-6 py-3 font-semibold text-right">Amount</th>
              <th className="px-6 py-3 font-semibold">Days waiting</th>
              <th className="px-6 py-3 font-semibold">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {items.map((item) => (
              <tr key={item.entry_id} className="hover:bg-[var(--background-muted)]/50 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap">{formatDateDisplay(item.initiated_date)}</td>
                <td className="px-6 py-4">{item.from_account}</td>
                <td className="px-6 py-4">{item.to_account}</td>
                <td className="px-6 py-4 text-right font-mono">{formatCurrencyLocale(item.amount, item.currency)}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <span>{item.days_outstanding}d</span>
                    {item.days_outstanding > OVERDUE_DAYS && (
                      <span className="badge badge-error inline-flex items-center gap-1" aria-label="warning overdue">
                        <AlertTriangle className="w-3 h-3" />
                        {item.days_outstanding}d
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">{item.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
