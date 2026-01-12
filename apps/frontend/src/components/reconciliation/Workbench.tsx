"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";

interface BankTransactionSummary {
  id: string;
  statement_id: string;
  txn_date: string;
  description: string;
  amount: number;
  direction: "IN" | "OUT";
  reference?: string | null;
  status: "pending" | "matched" | "unmatched";
}

interface JournalEntrySummary {
  id: string;
  entry_date: string;
  memo?: string | null;
  status: string;
  total_amount: number;
}

interface ReconciliationMatchResponse {
  id: string;
  bank_txn_id: string;
  journal_entry_ids: string[];
  match_score: number;
  score_breakdown: Record<string, number>;
  status: "auto_accepted" | "pending_review" | "accepted" | "rejected" | "superseded";
  transaction?: BankTransactionSummary | null;
  entries: JournalEntrySummary[];
}

interface ReconciliationMatchListResponse {
  items: ReconciliationMatchResponse[];
  total: number;
}

interface ReconciliationStatsResponse {
  total_transactions: number;
  matched_transactions: number;
  unmatched_transactions: number;
  pending_review: number;
  auto_accepted: number;
  match_rate: number;
  score_distribution: Record<string, number>;
}

interface AnomalyResponse {
  anomaly_type: string;
  severity: string;
  message: string;
}

export default function ReconciliationWorkbench() {
  const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
  const [queue, setQueue] = useState<ReconciliationMatchResponse[]>([]);
  const [selected, setSelected] = useState<ReconciliationMatchResponse | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [batching, setBatching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [statsData, pendingData] = await Promise.all([
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
        apiFetch<ReconciliationMatchListResponse>("/api/reconciliation/pending"),
      ]);
      setStats(statsData);
      setQueue(pendingData.items);
      setSelected((current) => {
        const hasCurrent = current != null && pendingData.items.some((i) => i.id === current.id);
        if (hasCurrent) {
          return current;
        }
        if (pendingData.items.length > 0) {
          return pendingData.items[0];
        }
        return null;
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load reconciliation data.");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAnomalies = useCallback(async (txnId: string) => {
    try {
      setAnomalies(await apiFetch<AnomalyResponse[]>(`/api/reconciliation/transactions/${txnId}/anomalies`));
    } catch {
      setAnomalies([]);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (selected?.transaction?.id) {
      fetchAnomalies(selected.transaction.id);
    } else {
      setAnomalies([]);
    }
  }, [fetchAnomalies, selected]);

  const runReconciliation = async () => {
    setRunning(true);
    try {
      await apiFetch("/api/reconciliation/run", { method: "POST", body: JSON.stringify({}) });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run reconciliation.");
    } finally {
      setRunning(false);
    }
  };

  const acceptMatch = async (matchId: string) => {
    try {
      await apiFetch(`/api/reconciliation/matches/${matchId}/accept`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept match.");
    }
  };

  const rejectMatch = async (matchId: string) => {
    try {
      await apiFetch(`/api/reconciliation/matches/${matchId}/reject`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject match.");
    }
  };

  const batchAccept = async () => {
    const highScoreIds = queue.filter((m) => m.match_score >= 80).map((m) => m.id);
    if (!highScoreIds.length) return;
    setBatching(true);
    try {
      await apiFetch("/api/reconciliation/batch-accept", {
        method: "POST",
        body: JSON.stringify({ match_ids: highScoreIds }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch accept failed.");
    } finally {
      setBatching(false);
    }
  };

  const distribution = useMemo(() => stats ? Object.entries(stats.score_distribution) : [], [stats]);
  const maxBucket = useMemo(() => stats ? Math.max(...Object.values(stats.score_distribution), 1) : 1, [stats]);

  return (
    <div className="p-6">
      {/* Header */}
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
        <div>
          <h1 className="page-title">Reconciliation Workbench</h1>
          <p className="page-description">Match statement activity to ledger entries with multi-dimensional scoring</p>
          <div className="flex flex-wrap gap-2 mt-4">
            <button onClick={runReconciliation} disabled={running} className="btn-primary">{running ? "Running..." : "Run Matching"}</button>
            <button onClick={batchAccept} disabled={batching} className="btn-secondary">{batching ? "Batching..." : "Batch Accept ≥ 80"}</button>
            <Link href="/reconciliation/unmatched" className="btn-secondary">Unmatched Studio</Link>
          </div>
          {error && <div className="mt-3 alert-error">{error}</div>}
        </div>

        {/* Stats Card */}
        <div className="card p-5 w-full max-w-sm">
          <div className="text-xs text-muted uppercase tracking-wide">Match Rate</div>
          <div className="flex items-end gap-2 mt-1">
            <span className="text-3xl font-semibold text-[var(--accent)]">{stats ? stats.match_rate.toFixed(1) : "0.0"}%</span>
            <span className="text-sm text-muted">{stats?.matched_transactions ?? 0} / {stats?.total_transactions ?? 0}</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-[var(--background-muted)] overflow-hidden">
            <div className="h-full bg-[var(--accent)] rounded-full transition-all" style={{ width: `${stats?.match_rate ?? 0}%` }} />
          </div>
          <div className="grid grid-cols-4 gap-2 mt-4 text-center">
            <div className="p-2 rounded-md bg-[var(--success-muted)]"><div className="text-xs text-muted">Auto</div><div className="font-semibold text-[var(--success)]">{stats?.auto_accepted ?? 0}</div></div>
            <div className="p-2 rounded-md bg-[var(--warning-muted)]"><div className="text-xs text-muted">Review</div><div className="font-semibold text-[var(--warning)]">{stats?.pending_review ?? 0}</div></div>
            <div className="p-2 rounded-md bg-[var(--background-muted)]"><div className="text-xs text-muted">None</div><div className="font-semibold">{stats?.unmatched_transactions ?? 0}</div></div>
            <div className="p-2 rounded-md bg-[var(--accent-muted)]"><div className="text-xs text-muted">Queue</div><div className="font-semibold text-[var(--accent)]">{queue.length}</div></div>
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid gap-4 lg:grid-cols-2 mt-6">
        {/* Review Queue */}
        <div className="card p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="font-semibold">Review Queue</h2>
            <span className="text-xs text-muted">{queue.length} items</span>
          </div>
          {loading ? <p className="text-sm text-muted">Loading...</p> :
            queue.length === 0 ? <p className="text-sm text-muted">No pending matches</p> : (
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {queue.map((match) => (
                  <button
                    key={match.id}
                    onClick={() => setSelected(match)}
                    className={`w-full text-left p-3 rounded-md transition-colors ${selected?.id === match.id ? "bg-[var(--accent-muted)] border border-[var(--accent)]" : "bg-[var(--background-muted)] hover:bg-[var(--background-muted)]/80"}`}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <div className="min-w-0">
                        <p className="font-medium text-sm truncate">{match.transaction?.description ?? "Transaction"}</p>
                        <p className="text-xs text-muted">{match.transaction?.txn_date} · {match.transaction?.direction === "IN" ? "In" : "Out"}</p>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="text-lg font-semibold text-[var(--accent)]">{match.match_score}</div>
                        <span className={`badge text-[10px] ${match.status === "auto_accepted" ? "badge-success" : match.status === "pending_review" ? "badge-warning" : "badge-muted"}`}>
                          {match.status.replace("_", " ")}
                        </span>
                      </div>
                    </div>
                    <div className="flex justify-between text-xs text-muted mt-2">
                      <span>{match.transaction?.amount?.toLocaleString() ?? "—"}</span>
                      <span>{match.entries.length} entries</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
        </div>

        {/* Match Detail */}
        <div className="card p-5">
          <h2 className="font-semibold mb-4">Match Detail</h2>
          {!selected ? <p className="text-sm text-muted">Select a match to review</p> : (
            <div className="space-y-4">
              <div className="p-3 rounded-md bg-[var(--background-muted)]">
                <div className="flex justify-between"><span className="text-sm font-medium">Transaction</span><span className="text-xs text-[var(--accent)]">Score {selected.match_score}</span></div>
                <div className="text-xl font-semibold mt-1 text-[var(--accent)]">{selected.transaction?.amount?.toLocaleString() ?? "—"}</div>
                <p className="text-sm text-muted">{selected.transaction?.description}</p>
                <p className="text-xs text-muted">{selected.transaction?.txn_date} · {selected.transaction?.direction === "IN" ? "In" : "Out"}</p>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {selected.entries.map((entry) => (
                  <div key={entry.id} className="p-3 rounded-md border border-[var(--border)]">
                    <div className="text-xs text-[var(--accent)] uppercase tracking-wide">Ledger Entry</div>
                    <p className="font-medium text-sm">{entry.memo || "Untitled"}</p>
                    <p className="text-xs text-muted">{entry.entry_date}</p>
                    <p className="font-semibold text-[var(--accent)]">{entry.total_amount.toLocaleString()}</p>
                  </div>
                ))}
              </div>

              <div className="p-3 rounded-md bg-[var(--background-muted)]">
                <p className="font-medium text-sm mb-2">Score Breakdown</p>
                <div className="space-y-1 text-xs">
                  {Object.entries(selected.score_breakdown).map(([key, value]) => (
                    <div key={key} className="flex justify-between"><span className="capitalize text-muted">{key.replace("_", " ")}</span><span className="font-semibold text-[var(--accent)]">{Number(value).toFixed(1)}</span></div>
                  ))}
                </div>
              </div>

              {anomalies.length > 0 && (
                <div className="p-3 rounded-md bg-[var(--warning-muted)] border border-[var(--warning)]/30">
                  <p className="font-medium text-sm text-[var(--warning)]">Anomaly Signals</p>
                  <ul className="mt-1 text-xs space-y-1">{anomalies.map((a) => <li key={a.anomaly_type}><strong className="uppercase">{a.severity}</strong>: {a.message}</li>)}</ul>
                </div>
              )}

              <div className="flex gap-2">
                <button onClick={() => acceptMatch(selected.id)} className="btn-primary flex-1">Accept</button>
                <button onClick={() => rejectMatch(selected.id)} className="btn-secondary flex-1">Reject</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Score Distribution */}
      <div className="card p-5 mt-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold">Score Distribution</h2>
          <span className="text-xs text-muted">Confidence bands</span>
        </div>
        <div className="flex flex-wrap items-end gap-4">
          {distribution.map(([label, value]) => (
            <div key={label} className="flex flex-col items-center gap-1">
              <div className="w-10 rounded-md bg-[var(--accent)]" style={{ height: `${20 + (value / maxBucket) * 80}px` }} />
              <div className="text-xs font-medium">{label}</div>
              <div className="text-xs text-muted">{value}</div>
            </div>
          ))}
          {!stats && <p className="text-sm text-muted">No data yet</p>}
        </div>
      </div>
    </div>
  );
}
