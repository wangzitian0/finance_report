"use client";

import { useCallback, useEffect, useState } from "react";
import DetailDialog from "@/components/ui/DetailDialog";
import { apiOperation } from "@/lib/api-client";
import { formatAmount, formatCurrencyLocale, multiplyAmount, sumAmounts } from "@/lib/audit/money";
import { formatDateDisplay, formatDateTimeDisplay } from "@/lib/date";
import { JournalEntry, JournalLine } from "@/lib/types";

interface AuditTrailRecord {
  timestamp: string;
  actor: string;
  action: string;
  old_value?: Record<string, unknown> | null;
  new_value?: Record<string, unknown> | null;
}

export function AuditTrailPanel({ transactionId }: { transactionId: string }) {
  const [records, setRecords] = useState<AuditTrailRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAuditTrail = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiOperation("get_transaction_audit_transactions__transaction_id__audit_get", {
        path: { transaction_id: transactionId },
      });
      setRecords(data.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit trail");
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => {
    void fetchAuditTrail();
  }, [fetchAuditTrail]);

  return (
    <section className="border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="bg-[var(--background-muted)]/50 px-4 py-2 border-b border-[var(--border)]">
        <h4 className="font-semibold">Audit Trail</h4>
      </div>
      {loading ? (
        <div className="p-4 text-sm text-muted">Loading audit trail...</div>
      ) : error ? (
        <div className="p-4 text-sm text-[var(--error)]">{error}</div>
      ) : records.length === 0 ? (
        <div className="p-4 text-sm text-muted">No audit records</div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {records.map((r) => (
            <div key={`${r.timestamp}-${r.actor}-${r.action}`} className="p-4 text-sm">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span className="badge badge-muted">{r.actor}</span>
                  <span className="font-medium">{r.action}</span>
                </div>
                <span className="text-xs text-muted">{formatDateTimeDisplay(r.timestamp)}</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-[var(--background-muted)]/40 p-2">
                  <span className="text-muted">Old:</span> {r.old_value ? JSON.stringify(r.old_value) : "—"}
                </div>
                <div className="rounded bg-[var(--background-muted)]/40 p-2">
                  <span className="text-muted">New:</span> {r.new_value ? JSON.stringify(r.new_value) : "—"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

interface JournalEntryDetailsModalProps {
  entry: JournalEntry | null;
  isOpen: boolean;
  onClose: () => void;
}

export default function JournalEntryDetailsModal({ entry, isOpen, onClose }: JournalEntryDetailsModalProps) {
  if (!entry) return null;

  const baseCurrency = "SGD";
  const baseAmount = (line: JournalLine) => {
    if (line.currency.toUpperCase() === baseCurrency) return line.amount;
    if (!line.fx_rate) return 0;
    return multiplyAmount(line.amount, line.fx_rate);
  };
  const totalDebits = entry.lines.filter((l) => l.direction === "DEBIT").map(baseAmount);
  const totalCredits = entry.lines.filter((l) => l.direction === "CREDIT").map(baseAmount);

  return (
    <DetailDialog isOpen={isOpen} onClose={onClose} title="Journal Entry Details" maxWidth="max-w-2xl">
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted mb-1">Date</p>
              <p className="font-medium">{formatDateDisplay(entry.entry_date)}</p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Status</p>
              <span
                className={`badge ${
                  entry.status === "posted"
                    ? "badge-success"
                    : entry.status === "reconciled"
                      ? "badge-primary"
                      : entry.status === "void"
                        ? "badge-error"
                        : "badge-muted"
                }`}
              >
                {entry.status}
              </span>
            </div>
          </div>
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted mb-1">Source Type</p>
              <p className="font-medium capitalize">{entry.source_type.replace("_", " ")}</p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Created At</p>
              <p className="font-medium">{new Date(entry.created_at).toLocaleString()}</p>
            </div>
          </div>
          <div className="col-span-2">
            <p className="text-xs text-muted mb-1">Memo</p>
            <p className="text-sm bg-[var(--background-muted)]/50 p-3 rounded-md border border-[var(--border)] italic">
              {entry.memo || "No memo"}
            </p>
          </div>
        </div>

        <div>
          <h4 className="font-semibold mb-3">Lines</h4>
          <div data-testid="journal-lines-mobile" className="space-y-3 md:hidden">
            {entry.lines.map((line) => (
              <div key={line.id} data-testid={`journal-line-mobile-${line.id}`} className="rounded-lg border border-[var(--border)] bg-[var(--background-card)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-medium uppercase text-muted">Account</p>
                    <p className="mt-1 break-all font-mono text-xs">{line.account_id}</p>
                  </div>
                  <span className={`badge flex-shrink-0 ${line.direction === "DEBIT" ? "badge-success" : "badge-error"}`}>{line.direction}</span>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs font-medium uppercase text-muted">Amount</p>
                    <p className={`mt-1 font-semibold ${line.direction === "DEBIT" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                      {formatCurrencyLocale(line.amount, line.currency)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase text-muted">Currency</p>
                    <p className="mt-1 text-muted">{line.currency}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase text-muted">FX Rate</p>
                    <p className="mt-1 text-muted">{line.fx_rate ? formatAmount(line.fx_rate, 6) : "1.000000"}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase text-muted">SGD Base</p>
                    <p className="mt-1 font-semibold">{formatCurrencyLocale(baseAmount(line), baseCurrency)}</p>
                  </div>
                </div>
              </div>
            ))}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--background-muted)]/30 p-4 text-sm">
              <p className="text-xs font-medium uppercase text-muted">Totals</p>
              <div className="mt-2 flex items-center justify-between gap-3 text-[var(--success)]">
                <span>DR</span>
                <span className="font-semibold">{formatCurrencyLocale(sumAmounts(totalDebits), baseCurrency)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between gap-3 text-[var(--error)]">
                <span>CR</span>
                <span className="font-semibold">{formatCurrencyLocale(sumAmounts(totalCredits), baseCurrency)}</span>
              </div>
            </div>
          </div>
          <div className="hidden border border-[var(--border)] rounded-lg overflow-x-auto md:block">
            <table className="w-full min-w-[640px] text-sm text-left">
              <thead className="bg-[var(--background-muted)]/50 text-muted font-medium border-b border-[var(--border)]">
                <tr>
                  <th className="px-4 py-2">Account</th>
                  <th className="px-4 py-2">Direction</th>
                  <th className="px-4 py-2 text-right">Amount</th>
                  <th className="px-4 py-2">Currency</th>
                  <th className="px-4 py-2 text-right">FX Rate</th>
                  <th className="px-4 py-2 text-right">SGD Base</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {entry.lines.map((line) => (
                  <tr key={line.id} className={line.direction === "DEBIT" ? "bg-[var(--success-muted)]/5" : "bg-[var(--error-muted)]/5"}>
                    <td className="px-4 py-3 font-mono text-xs whitespace-nowrap">{line.account_id}</td>
                    <td className="px-4 py-3">
                      <span className={`badge ${line.direction === "DEBIT" ? "badge-success" : "badge-error"}`}>{line.direction}</span>
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold whitespace-nowrap ${line.direction === "DEBIT" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                      {formatCurrencyLocale(line.amount, line.currency)}
                    </td>
                    <td className="px-4 py-3 text-muted">{line.currency}</td>
                    <td className="px-4 py-3 text-right text-muted">{line.fx_rate ? formatAmount(line.fx_rate, 6) : "1.000000"}</td>
                    <td className="px-4 py-3 text-right font-semibold whitespace-nowrap">{formatCurrencyLocale(baseAmount(line), baseCurrency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="bg-[var(--background-muted)]/30 font-bold border-t border-[var(--border)]">
                <tr>
                  <td colSpan={5} className="px-4 py-3 text-right text-muted">SGD Base Totals</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col items-end gap-1">
                      <div className="text-[var(--success)]"><span className="text-[10px] uppercase mr-1">DR:</span>{formatCurrencyLocale(sumAmounts(totalDebits), baseCurrency)}</div>
                      <div className="text-[var(--error)]"><span className="text-[10px] uppercase mr-1">CR:</span>{formatCurrencyLocale(sumAmounts(totalCredits), baseCurrency)}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted">{baseCurrency}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
        <AuditTrailPanel transactionId={entry.id} />
      </div>
    </DetailDialog>
  );
}
