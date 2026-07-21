"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { AuditBackLink } from "@/components/audit/AuditBackLink";
import { LoadingState } from "@/components/ui";
import { apiOperation } from "@/lib/api-client";
import { ProcessingPendingListResponse } from "@/lib/types";
import { formatDateDisplay } from "@/lib/date";
import { formatCurrencyLocale } from "@/lib/audit/money";

export default function ProcessingPage() {
  const [data, setData] = useState<ProcessingPendingListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchPending() {
      try {
        const response = await apiOperation(
          "list_processing_pending_accounts_processing_pending_get",
        );
        setData(response);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load pending transfers",
        );
      } finally {
        setLoading(false);
      }
    }
    fetchPending();
  }, []);

  return (
    <div className="p-6">
      <div className="mb-4">
        <AuditBackLink />
      </div>

      <div className="page-header mb-6">
        <h1 className="page-title">Processing Transfers</h1>
        <p className="page-description">
          Transactions currently in flight between accounts
        </p>
      </div>

      {loading ? (
        <LoadingState label="Loading transfers" />
      ) : error ? (
        <div className="card p-8 text-center text-[var(--error)] border-[var(--error)]/30">
          <p>{error}</p>
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="card p-8 text-center text-muted">
          <p>No pending transfers found.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[var(--background-muted)] border-b border-[var(--border)]">
                <tr>
                  <th className="px-6 py-3 font-semibold">Initiated Date</th>
                  <th className="px-6 py-3 font-semibold">From</th>
                  <th className="px-6 py-3 font-semibold">To</th>
                  <th className="px-6 py-3 font-semibold text-right">Amount</th>
                  <th className="px-6 py-3 font-semibold">Days Outstanding</th>
                  <th className="px-6 py-3 font-semibold">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {data.items.map((item) => (
                  <tr
                    key={item.entry_id}
                    className="hover:bg-[var(--background-muted)]/50 transition-colors"
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      {formatDateDisplay(item.initiated_date)}
                    </td>
                    <td className="px-6 py-4">{item.from_account}</td>
                    <td className="px-6 py-4">{item.to_account}</td>
                    <td className="px-6 py-4 text-right font-mono">
                      {formatCurrencyLocale(item.amount, item.currency)}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span>{item.days_outstanding}d</span>
                        {item.days_outstanding > 7 && (
                          <span
                            className="badge badge-error inline-flex items-center gap-1"
                            aria-label="warning overdue"
                          >
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
        </div>
      )}
    </div>
  );
}
