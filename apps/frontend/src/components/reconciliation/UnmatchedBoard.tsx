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

interface UnmatchedTransactionsResponse { items: BankTransactionSummary[]; total: number; }
interface JournalEntrySummary { id: string; entry_date: string; memo?: string | null; status: string; total_amount: number; }

export default function UnmatchedBoard() {
  const [items, setItems] = useState<BankTransactionSummary[]>([]);
  const [selected, setSelected] = useState<BankTransactionSummary | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [createdEntry, setCreatedEntry] = useState<JournalEntrySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<UnmatchedTransactionsResponse>("/api/reconciliation/unmatched");
      setItems(data.items);
      setSelected((c) => (c && data.items.some((i) => i.id === c.id) ? c : data.items[0] ?? null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load unmatched transactions.");
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { setCreatedEntry(null); }, [selected?.id]);

  const createEntry = async (txnId: string) => {
    setCreating(txnId);
    try {
      const entry = await apiFetch<JournalEntrySummary>(`/api/reconciliation/unmatched/${txnId}/create-entry`, { method: "POST" });
      setCreatedEntry(entry);
      setError(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create entry.");
    } finally { setCreating(null); }
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
    setItems((prev) => prev.filter((i) => i.id !== txnId));
    if (selected?.id === txnId) {
      setSelected(null);
    }
  };

  const summary = useMemo(() => ({ total: items.length, flagged: flagged.size }), [flagged.size, items.length]);
  const aiPrompt = useMemo(() => {
    if (!selected) return null;
    const { description, txn_date, amount, direction } = selected;
    return encodeURIComponent(
      `Help me interpret this transaction: ${description} on ${txn_date}, amount ${amount} (${direction === "IN" ? "inflow" : "outflow"}). Why might it be unmatched?`,
    );
  }, [selected?.description, selected?.txn_date, selected?.amount, selected?.direction]);

  return (
    <div className="p-6">
      <div className="page-header flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Unmatched Transactions</h1>
          <p className="page-description">Triage unmatched transactions and create manual journal entries</p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/reconciliation" className="btn-secondary text-sm">← Workbench</Link>
          <span className="badge badge-warning">{summary.total} unmatched · {summary.flagged} flagged</span>
        </div>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="font-semibold">Unmatched List</h2>
            <span className="text-xs text-muted">{items.length} records</span>
          </div>
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => setSelected(item)}
                className={`w-full text-left p-3 rounded-md transition-colors ${selected?.id === item.id ? "bg-[var(--accent-muted)] border border-[var(--accent)]" : "bg-[var(--background-muted)] hover:bg-[var(--background-muted)]/80"}`}
              >
                <div className="flex justify-between items-start gap-2">
                  <div className="min-w-0">
                    <p className="font-medium text-sm truncate">{item.description}</p>
                    <p className="text-xs text-muted">{item.txn_date} · {item.direction === "IN" ? "In" : "Out"}</p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="font-semibold text-[var(--accent)]">{item.amount?.toLocaleString()}</div>
                    {flagged.has(item.id) && <span className="badge badge-warning text-[10px]">Flagged</span>}
                  </div>
                </div>
              </button>
            ))}
            {items.length === 0 && <div className="p-8 text-center text-muted text-sm">No unmatched transactions</div>}
          </div>
        </div>

        <div className="card p-5">
          <h2 className="font-semibold mb-4">Transaction Detail</h2>
          {!selected ? <p className="text-sm text-muted">Select a transaction to review</p> : (
            <div className="space-y-4">
              <div className="p-3 rounded-md bg-[var(--background-muted)]">
                <p className="font-medium">{selected.description}</p>
                <p className="text-xs text-muted">{selected.txn_date} · {selected.direction === "IN" ? "Inflow" : "Outflow"}</p>
                <p className="text-xl font-semibold text-[var(--accent)] mt-1">{selected.amount?.toLocaleString()}</p>
                {selected.reference && <p className="text-xs text-muted">Ref: {selected.reference}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
                <button onClick={() => createEntry(selected.id)} disabled={creating === selected.id} className="btn-primary">{creating === selected.id ? "Creating..." : "Create Entry"}</button>
                {aiPrompt && <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary">Ask AI</Link>}
                <button onClick={() => toggleFlag(selected.id)} className="btn-secondary">{flagged.has(selected.id) ? "Unflag" : "Flag"}</button>
                <button onClick={() => removeFromList(selected.id)} className="btn-secondary">Ignore</button>
              </div>

              {createdEntry && (
                <div className="p-3 rounded-md bg-[var(--success-muted)] border border-[var(--success)]/30 text-sm">
                  Created entry <strong>{createdEntry.id}</strong> · {createdEntry.total_amount?.toLocaleString()} on {createdEntry.entry_date}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
