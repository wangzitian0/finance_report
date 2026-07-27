"use client";

import { useCallback, useEffect, useState } from "react";

import { apiOperation } from "@/lib/api-client";
import { formatDateTimeDisplay } from "@/lib/date";

interface AuditTrailRecord {
  timestamp: string;
  actor: string;
  action: string;
  old_value?: Record<string, unknown> | null;
  new_value?: Record<string, unknown> | null;
}

interface AuditTrailPanelProps {
  transactionId: string;
}

function formatValue(value: Record<string, unknown> | null | undefined) {
  if (!value) return "—";
  return JSON.stringify(value);
}

export default function AuditTrailPanel({
  transactionId,
}: AuditTrailPanelProps) {
  const [records, setRecords] = useState<AuditTrailRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAuditTrail = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiOperation(
        "get_transaction_audit_transactions__transaction_id__audit_get",
        {
          path: { transaction_id: transactionId },
        },
      );
      setRecords(data.items);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load audit trail",
      );
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => {
    fetchAuditTrail();
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
          {records.map((record) => (
            <div
              key={`${record.timestamp}-${record.actor}-${record.action}`}
              className="p-4 text-sm"
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span className="badge badge-muted">{record.actor}</span>
                  <span className="font-medium">{record.action}</span>
                </div>
                <span className="text-xs text-muted">
                  {formatDateTimeDisplay(record.timestamp)}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-[var(--background-muted)]/40 p-2">
                  <span className="text-muted">Old:</span>{" "}
                  {formatValue(record.old_value)}
                </div>
                <div className="rounded bg-[var(--background-muted)]/40 p-2">
                  <span className="text-muted">New:</span>{" "}
                  {formatValue(record.new_value)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
