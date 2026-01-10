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

const statusTone: Record<string, string> = {
  auto_accepted: "bg-emerald-100 text-emerald-800",
  pending_review: "bg-amber-100 text-amber-800",
  accepted: "bg-teal-100 text-teal-800",
  rejected: "bg-rose-100 text-rose-800",
  superseded: "bg-slate-100 text-slate-600",
};

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
        if (current && pendingData.items.some((item) => item.id === current.id)) {
          return current;
        }
        return pendingData.items[0] ?? null;
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
      const data = await apiFetch<AnomalyResponse[]>(
        `/api/reconciliation/transactions/${txnId}/anomalies`
      );
      setAnomalies(data);
    } catch {
      setAnomalies([]);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
      await apiFetch("/api/reconciliation/run", {
        method: "POST",
        body: JSON.stringify({}),
      });
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

  const distribution = useMemo(() => {
    if (!stats) return [];
    return Object.entries(stats.score_distribution);
  }, [stats]);

  const maxBucket = useMemo(() => {
    if (!stats) return 1;
    return Math.max(...Object.values(stats.score_distribution), 1);
  }, [stats]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#fef3c7_0%,#f8f4ed_55%,#e2e8f0_100%)] text-[#0f1f17]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-24 right-[-4rem] h-64 w-64 rounded-full bg-[#fcdba3] blur-3xl opacity-70"></div>
        <div className="pointer-events-none absolute bottom-[-6rem] left-[-4rem] h-72 w-72 rounded-full bg-[#a7f3d0] blur-3xl opacity-60"></div>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(#0f1f17_0.5px,transparent_0.5px)] opacity-10 [background-size:14px_14px]"></div>

        <div className="relative z-10 mx-auto max-w-6xl px-6 py-10">
          <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-4 animate-rise">
              <p className="text-xs uppercase tracking-[0.4em] text-emerald-700">Ledger Atlas</p>
              <h1 className="text-4xl sm:text-5xl font-semibold text-[#101a16]">
                Reconciliation Workbench
              </h1>
              <p className="max-w-xl text-base text-[#334136]">
                Match statement activity to ledger entries with multi-dimensional scoring, contextual
                review, and anomaly signals.
              </p>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <button
                  onClick={runReconciliation}
                  disabled={running}
                  className="rounded-full bg-[#0f766e] px-5 py-2 text-white shadow-lg shadow-emerald-200/50 transition hover:bg-[#115e59] disabled:opacity-60"
                >
                  {running ? "Running..." : "Run Matching"}
                </button>
                <button
                  onClick={batchAccept}
                  disabled={batching}
                  className="rounded-full border border-[#0f766e] px-5 py-2 text-[#0f766e] transition hover:bg-[#0f766e]/10 disabled:opacity-60"
                >
                  {batching ? "Batching..." : "Batch Accept ≥ 80"}
                </button>
                <Link
                  href="/reconciliation/unmatched"
                  className="rounded-full border border-[#7c4a1f] px-5 py-2 text-[#7c4a1f] transition hover:bg-[#7c4a1f]/10"
                >
                  Unmatched Studio
                </Link>
              </div>
              {error && (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              )}
            </div>

            <div className="w-full max-w-md rounded-3xl border border-white/70 bg-white/60 p-6 shadow-xl shadow-amber-100/70 backdrop-blur animate-rise">
              <div className="text-xs uppercase tracking-[0.3em] text-emerald-600">Match Rate</div>
              <div className="mt-2 flex items-end gap-3">
                <span className="text-4xl font-semibold text-[#0f766e]">
                  {stats ? stats.match_rate.toFixed(1) : "0.0"}%
                </span>
                <span className="text-sm text-[#6b7c71]">
                  {stats ? stats.matched_transactions : 0} matched / {stats ? stats.total_transactions : 0}
                </span>
              </div>
              <div className="mt-4 h-3 overflow-hidden rounded-full bg-[#e5e7eb]">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-teal-500 to-emerald-700 animate-sweep"
                  style={{ width: `${stats?.match_rate ?? 0}%` }}
                ></div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-4 text-sm">
                <div className="rounded-2xl bg-emerald-50 px-4 py-3">
                  <p className="text-xs uppercase text-emerald-500">Auto</p>
                  <p className="text-lg font-semibold text-emerald-800">
                    {stats?.auto_accepted ?? 0}
                  </p>
                </div>
                <div className="rounded-2xl bg-amber-50 px-4 py-3">
                  <p className="text-xs uppercase text-amber-500">Review</p>
                  <p className="text-lg font-semibold text-amber-800">
                    {stats?.pending_review ?? 0}
                  </p>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <p className="text-xs uppercase text-slate-500">Unmatched</p>
                  <p className="text-lg font-semibold text-slate-700">
                    {stats?.unmatched_transactions ?? 0}
                  </p>
                </div>
                <div className="rounded-2xl bg-[#fef3c7] px-4 py-3">
                  <p className="text-xs uppercase text-[#b45309]">Queue</p>
                  <p className="text-lg font-semibold text-[#7c4a1f]">{queue.length}</p>
                </div>
              </div>
            </div>
          </header>

          <section className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
            <div className="rounded-3xl border border-white/70 bg-white/70 p-6 shadow-lg shadow-emerald-100/50">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-2xl font-semibold text-[#111c17]">Review Queue</h2>
                  <p className="text-sm text-[#5f6f63]">Pending matches waiting for confirmation.</p>
                </div>
                <span className="text-xs uppercase tracking-[0.3em] text-emerald-500">
                  {queue.length} items
                </span>
              </div>

              {loading ? (
                <div className="mt-6 text-sm text-[#6b7c71]">Loading matches...</div>
              ) : queue.length === 0 ? (
                <div className="mt-6 text-sm text-[#6b7c71]">No pending matches right now.</div>
              ) : (
                <div className="mt-6 space-y-3">
                  {queue.map((match) => (
                    <button
                      key={match.id}
                      onClick={() => setSelected(match)}
                      className={`w-full rounded-2xl border px-4 py-4 text-left transition ${
                        selected?.id === match.id
                          ? "border-emerald-400 bg-emerald-50 shadow-md shadow-emerald-100"
                          : "border-transparent bg-white/70 hover:border-emerald-200"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-sm font-medium text-[#1f2a24]">
                            {match.transaction?.description ?? "Transaction"}
                          </p>
                          <p className="text-xs text-[#6b7c71]">
                            {match.transaction?.txn_date ?? "—"} ·{" "}
                            {match.transaction?.direction === "IN" ? "Inflow" : "Outflow"}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-lg font-semibold text-[#0f766e]">
                            {match.match_score}
                          </p>
                          <span
                            className={`mt-1 inline-flex rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${
                              statusTone[match.status]
                            }`}
                          >
                            {match.status.replace("_", " ")}
                          </span>
                        </div>
                      </div>
                      <div className="mt-3 flex items-center justify-between text-xs text-[#6b7c71]">
                        <span>
                          Amount: {match.transaction?.amount?.toLocaleString() ?? "—"}
                        </span>
                        <span>{match.entries.length} candidate entries</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-white/70 bg-white/70 p-6 shadow-lg shadow-amber-100/50">
              <h2 className="text-2xl font-semibold text-[#111c17]">Match Detail</h2>
              <p className="text-sm text-[#5f6f63]">Score breakdown and ledger context.</p>

              {!selected ? (
                <div className="mt-6 text-sm text-[#6b7c71]">Select a match to review.</div>
              ) : (
                <div className="mt-6 space-y-5">
                  <div className="rounded-2xl bg-[#f8faf8] p-4">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium text-[#2a3a31]">Transaction</p>
                      <span className="text-xs uppercase tracking-[0.2em] text-emerald-500">
                        Score {selected.match_score}
                      </span>
                    </div>
                    <div className="mt-2 text-lg font-semibold text-[#0f766e]">
                      {selected.transaction?.amount?.toLocaleString() ?? "—"}
                    </div>
                    <p className="text-sm text-[#5f6f63]">
                      {selected.transaction?.description ?? "—"}
                    </p>
                    <p className="text-xs text-[#7b8b7f]">
                      {selected.transaction?.txn_date ?? "—"} ·{" "}
                      {selected.transaction?.direction === "IN" ? "Inflow" : "Outflow"}
                    </p>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    {selected.entries.map((entry) => (
                      <div
                        key={entry.id}
                        className="rounded-2xl border border-emerald-100 bg-white px-4 py-3"
                      >
                        <p className="text-xs uppercase tracking-[0.2em] text-emerald-500">
                          Ledger Entry
                        </p>
                        <p className="text-sm font-medium text-[#223029]">
                          {entry.memo || "Untitled entry"}
                        </p>
                        <p className="text-xs text-[#6b7c71]">{entry.entry_date}</p>
                        <p className="text-sm font-semibold text-[#0f766e]">
                          {entry.total_amount.toLocaleString()}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-2xl bg-white px-4 py-4">
                    <p className="text-sm font-medium text-[#223029]">Score Breakdown</p>
                    <div className="mt-3 space-y-2 text-xs text-[#5f6f63]">
                      {Object.entries(selected.score_breakdown).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between">
                          <span className="capitalize">{key.replace("_", " ")}</span>
                          <span className="font-semibold text-[#0f766e]">
                            {Number(value).toFixed(1)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {anomalies.length > 0 && (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
                      <p className="text-sm font-medium text-[#7c4a1f]">Anomaly Signals</p>
                      <ul className="mt-2 space-y-2 text-xs text-[#7c4a1f]">
                        {anomalies.map((anomaly) => (
                          <li key={anomaly.anomaly_type}>
                            <strong className="uppercase tracking-[0.2em]">
                              {anomaly.severity}
                            </strong>
                            : {anomaly.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-3">
                    <button
                      onClick={() => selected && acceptMatch(selected.id)}
                      className="rounded-full bg-emerald-600 px-6 py-2 text-sm text-white shadow-md shadow-emerald-200/60 transition hover:bg-emerald-700"
                    >
                      Accept Match
                    </button>
                    <button
                      onClick={() => selected && rejectMatch(selected.id)}
                      className="rounded-full border border-rose-200 px-6 py-2 text-sm text-rose-700 transition hover:bg-rose-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="mt-10 rounded-3xl border border-white/70 bg-white/70 p-6 shadow-lg shadow-slate-100/60">
            <div className="flex items-center justify-between">
              <h2 className="text-2xl font-semibold text-[#111c17]">Score Distribution</h2>
              <span className="text-xs uppercase tracking-[0.3em] text-emerald-500">
                Confidence bands
              </span>
            </div>
            <div className="mt-6 flex flex-wrap items-end gap-6">
              {distribution.map(([label, value], index) => (
                <div key={label} className="flex flex-col items-center gap-2">
                  <div
                    className="w-12 rounded-2xl bg-gradient-to-t from-emerald-500 to-amber-300"
                    style={{
                      height: `${24 + (value / maxBucket) * 120}px`,
                      opacity: 0.8 + index * 0.05,
                    }}
                  ></div>
                  <div className="text-xs font-semibold text-[#374236]">{label}</div>
                  <div className="text-xs text-[#7b8b7f]">{value}</div>
                </div>
              ))}
              {!stats && <div className="text-sm text-[#6b7c71]">No data yet.</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
