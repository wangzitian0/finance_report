"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import {
  ReconciliationMatchListResponse,
  ReconciliationMatchResponse,
  ReconciliationStatsResponse
} from "@/lib/types";

interface AnomalyResponse {
  anomaly_type: string;
  severity: string;
  message: string;
}

export default function ReconciliationWorkbench() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ReconciliationMatchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: stats, error: statsError } = useQuery({
    queryKey: ["reconciliation", "stats"],
    queryFn: () => apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
  });

  const { data: pendingData, isLoading, error: pendingError } = useQuery({
    queryKey: ["reconciliation", "pending"],
    queryFn: () => apiFetch<ReconciliationMatchListResponse>("/api/reconciliation/pending"),
  });

  useEffect(() => {
    if (!pendingData?.items) return;

    const items = pendingData.items;

    if (items.length === 0) {
      if (selected !== null) {
        setSelected(null);
      }
      return;
    }

    const existingSelection = selected && items.find((item) => item.id === selected.id);

    if (existingSelection) {
      if (existingSelection !== selected) {
        setSelected(existingSelection);
      }
    } else {
      setSelected(items[0]);
    }
  }, [pendingData, selected]);

  useEffect(() => {
    if (statsError) {
      setError(`Failed to load reconciliation stats: ${statsError.message}`);
    } else if (pendingError) {
      setError(`Failed to load pending matches: ${pendingError.message}`);
    }
  }, [statsError, pendingError]);

  const { data: anomalies = [] } = useQuery({
    queryKey: ["reconciliation", "anomalies", selected?.transaction?.id],
    queryFn: () => apiFetch<AnomalyResponse[]>(`/api/reconciliation/transactions/${selected!.transaction!.id}/anomalies`),
    enabled: !!selected?.transaction?.id,
  });

  const runReconciliationMutation = useMutation({
    mutationFn: () => apiFetch("/api/reconciliation/run", { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  const acceptMatchMutation = useMutation({
    mutationFn: (matchId: string) => apiFetch(`/api/reconciliation/matches/${matchId}/accept`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(`Failed to accept match: ${err.message}`);
    },
  });

  const rejectMatchMutation = useMutation({
    mutationFn: (matchId: string) => apiFetch(`/api/reconciliation/matches/${matchId}/reject`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(`Failed to reject match: ${err.message}`);
    },
  });

  const batchAcceptMutation = useMutation({
    mutationFn: (matchIds: string[]) => apiFetch("/api/reconciliation/batch-accept", {
      method: "POST",
      body: JSON.stringify({ match_ids: matchIds }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      setError(null);
    },
    onError: (err: Error) => {
      setError(`Batch accept failed: ${err.message}`);
    },
  });

  const queue = pendingData?.items ?? [];
  const highScoreIds = queue.filter((m) => m.match_score >= 80).map((m) => m.id);

  const distribution = useMemo(() => stats ? Object.entries(stats.score_distribution) : [], [stats]);
  const maxBucket = useMemo(() => stats ? Math.max(...Object.values(stats.score_distribution), 1) : 1, [stats]);

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
        <div>
          <h1 className="page-title">Reconciliation Workbench</h1>
          <p className="page-description">Match statement activity to ledger entries with multi-dimensional scoring</p>
          <div className="flex flex-wrap gap-2 mt-4">
            <button
              onClick={() => runReconciliationMutation.mutate()}
              disabled={runReconciliationMutation.isPending}
              className="btn-primary"
            >
              {runReconciliationMutation.isPending ? "Running..." : "Run Matching"}
            </button>
            <button
              onClick={() => batchAcceptMutation.mutate(highScoreIds)}
              disabled={batchAcceptMutation.isPending || highScoreIds.length === 0}
              className="btn-secondary"
            >
              {batchAcceptMutation.isPending ? "Batching..." : "Batch Accept ≥ 80"}
            </button>
            <Link href="/reconciliation/unmatched" className="btn-secondary">Unmatched Studio</Link>
          </div>
          {error && <div className="mt-3 alert-error">{error}</div>}
        </div>

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

      <div className="grid gap-4 lg:grid-cols-2 mt-6">
        <div className="card p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="font-semibold">Review Queue</h2>
            <span className="text-xs text-muted">{queue.length} items</span>
          </div>
          {isLoading ? <p className="text-sm text-muted">Loading...</p> :
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
                <button
                  onClick={() => acceptMatchMutation.mutate(selected.id)}
                  disabled={acceptMatchMutation.isPending}
                  className="btn-primary flex-1"
                >
                  {acceptMatchMutation.isPending ? "Accepting..." : "Accept"}
                </button>
                <button
                  onClick={() => rejectMatchMutation.mutate(selected.id)}
                  disabled={rejectMatchMutation.isPending}
                  className="btn-secondary flex-1"
                >
                  {rejectMatchMutation.isPending ? "Rejecting..." : "Reject"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

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
