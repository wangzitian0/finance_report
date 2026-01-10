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

interface UnmatchedTransactionsResponse {
  items: BankTransactionSummary[];
  total: number;
}

interface JournalEntrySummary {
  id: string;
  entry_date: string;
  memo?: string | null;
  status: string;
  total_amount: number;
}

export default function UnmatchedBoard() {
  const [items, setItems] = useState<BankTransactionSummary[]>([]);
  const [selected, setSelected] = useState<BankTransactionSummary | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [createdEntry, setCreatedEntry] = useState<JournalEntrySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<UnmatchedTransactionsResponse>(
        "/api/reconciliation/unmatched"
      );
      setItems(data.items);
      setSelected((current) => {
        if (current && data.items.some((item) => item.id === current.id)) {
          return current;
        }
        return data.items[0] ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load unmatched transactions.");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    setCreatedEntry(null);
  }, [selected?.id]);

  const createEntry = async (txnId: string) => {
    setCreating(txnId);
    try {
      const entry = await apiFetch<JournalEntrySummary>(
        `/api/reconciliation/unmatched/${txnId}/create-entry`,
        { method: "POST" }
      );
      setCreatedEntry(entry);
      setError(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create entry.");
    } finally {
      setCreating(null);
    }
  };

  const toggleFlag = (txnId: string) => {
    setFlagged((prev) => {
      const next = new Set(prev);
      if (next.has(txnId)) {
        next.delete(txnId);
      } else {
        next.add(txnId);
      }
      return next;
    });
  };

  const removeFromList = (txnId: string) => {
    setItems((prev) => prev.filter((item) => item.id !== txnId));
    if (selected?.id === txnId) {
      setSelected(null);
    }
  };

  const summary = useMemo(() => {
    return {
      total: items.length,
      flagged: flagged.size,
    };
  }, [flagged.size, items.length]);

  return (
    <div className="min-h-screen bg-[#f7f3ea] text-[#171f1b]">
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-16 left-[-6rem] h-56 w-56 rounded-full bg-[#fde68a] blur-3xl opacity-60"></div>
        <div className="pointer-events-none absolute bottom-[-8rem] right-[-2rem] h-72 w-72 rounded-full bg-[#bae6fd] blur-3xl opacity-60"></div>
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(15,118,110,0.1),transparent,rgba(217,119,6,0.15))] opacity-80"></div>

        <div className="relative z-10 mx-auto max-w-6xl px-6 py-10">
          <header className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between animate-rise">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-[#b45309]">
                Unmatched Studio
              </p>
              <h1 className="text-4xl font-semibold text-[#13201a]">
                Triage &amp; Manual Entry
              </h1>
              <p className="mt-2 max-w-lg text-sm text-[#5f6f63]">
                Review unmatched transactions, generate balanced entries, and mark edge cases for
                later follow-up.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <Link
                href="/reconciliation"
                className="rounded-full border border-[#0f766e] px-5 py-2 text-[#0f766e] transition hover:bg-[#0f766e]/10"
              >
                Back to Workbench
              </Link>
              <div className="rounded-full bg-white/70 px-4 py-2 text-[#0f766e] shadow-md">
                {summary.total} unmatched · {summary.flagged} flagged
              </div>
            </div>
          </header>

          {error && (
            <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          <section className="mt-8 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="rounded-3xl border border-white/60 bg-white/70 p-6 shadow-lg">
              <div className="flex items-center justify-between">
                <h2 className="text-2xl font-semibold text-[#111c17]">Unmatched List</h2>
                <span className="text-xs uppercase tracking-[0.3em] text-[#0f766e]">
                  {items.length} records
                </span>
              </div>
              <div className="mt-5 space-y-3">
                {items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setSelected(item)}
                    className={`w-full rounded-2xl border px-4 py-4 text-left transition ${
                      selected?.id === item.id
                        ? "border-[#0f766e] bg-emerald-50 shadow-md shadow-emerald-100"
                        : "border-transparent bg-white/80 hover:border-emerald-100"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm font-medium text-[#1f2a24]">{item.description}</p>
                        <p className="text-xs text-[#6b7c71]">
                          {item.txn_date} · {item.direction === "IN" ? "Inflow" : "Outflow"}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-semibold text-[#0f766e]">
                          {item.amount?.toLocaleString()}
                        </p>
                        {flagged.has(item.id) && (
                          <span className="mt-1 inline-flex rounded-full bg-amber-100 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-700">
                            Flagged
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
                {items.length === 0 && (
                  <div className="rounded-2xl border border-dashed border-emerald-100 px-4 py-8 text-center text-sm text-[#6b7c71]">
                    No unmatched transactions right now.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-white/60 bg-white/70 p-6 shadow-lg">
              <h2 className="text-2xl font-semibold text-[#111c17]">Transaction Detail</h2>
              {!selected ? (
                <div className="mt-5 text-sm text-[#6b7c71]">
                  Select a transaction to review.
                </div>
              ) : (
                <div className="mt-5 space-y-5">
                  <div className="rounded-2xl bg-[#f8faf8] p-4">
                    <p className="text-sm font-medium text-[#223029]">{selected.description}</p>
                    <p className="text-xs text-[#6b7c71]">
                      {selected.txn_date} · {selected.direction === "IN" ? "Inflow" : "Outflow"}
                    </p>
                    <p className="mt-2 text-lg font-semibold text-[#0f766e]">
                      {selected.amount?.toLocaleString()}
                    </p>
                    {selected.reference && (
                      <p className="text-xs text-[#7b8b7f]">Ref: {selected.reference}</p>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-3">
                    <button
                      onClick={() => createEntry(selected.id)}
                      disabled={creating === selected.id}
                      className="rounded-full bg-[#0f766e] px-6 py-2 text-sm text-white shadow-md shadow-emerald-200/60 transition hover:bg-[#115e59] disabled:opacity-60"
                    >
                      {creating === selected.id ? "Creating..." : "Create Entry"}
                    </button>
                    <button
                      onClick={() => toggleFlag(selected.id)}
                      className="rounded-full border border-amber-200 px-6 py-2 text-sm text-amber-700 transition hover:bg-amber-50"
                    >
                      {flagged.has(selected.id) ? "Unflag" : "Flag"}
                    </button>
                    <button
                      onClick={() => removeFromList(selected.id)}
                      className="rounded-full border border-slate-200 px-6 py-2 text-sm text-slate-600 transition hover:bg-slate-50"
                    >
                      Ignore
                    </button>
                  </div>

                  {createdEntry && (
                    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-800">
                      Created entry <strong>{createdEntry.id}</strong> ·{" "}
                      {createdEntry.total_amount?.toLocaleString()} on {createdEntry.entry_date}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
