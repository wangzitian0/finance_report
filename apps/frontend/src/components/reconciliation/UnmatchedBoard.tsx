"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { BackLink } from "@/components/ui/BackLink";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import type {
  BankStatementTransactionSummary,
  JournalEntrySummary,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

type CreatedJournalEntrySummary = JournalEntrySummary & { currency?: string | null };
interface BatchCreateEntriesResponse { created_count: number; }

const FLAGGED_STORAGE_KEY = "finance-unmatched-flagged";

function loadFlaggedFromStorage(): Set<string> {
  try {
    if (typeof window === "undefined") return new Set();
    const stored = localStorage.getItem(FLAGGED_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        return new Set(parsed);
      }
    }
  } catch (error) {
    console.warn("[UnmatchedBoard] Failed to load flagged state:", error);
  }
  return new Set();
}

function saveFlaggedToStorage(flagged: Set<string>): void {
  try {
    if (typeof window === "undefined") return;
    localStorage.setItem(FLAGGED_STORAGE_KEY, JSON.stringify([...flagged]));
  } catch (error) {
    console.warn("[UnmatchedBoard] Failed to save flagged state:", error);
  }
}

export default function UnmatchedBoard() {
  const [items, setItems] = useState<BankStatementTransactionSummary[]>([]);
  const [selected, setSelected] = useState<BankStatementTransactionSummary | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [createdEntry, setCreatedEntry] = useState<CreatedJournalEntrySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<Set<string>>(() => loadFlaggedFromStorage());
  const [creatingAll, setCreatingAll] = useState(false);
  const [confirmCreateAllOpen, setConfirmCreateAllOpen] = useState(false);
  const [batchCreatedCount, setBatchCreatedCount] = useState<number | null>(null);

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
    setBatchCreatedCount(null);
    const createdFrom = selected;
    try {
      const entry = await apiFetch<CreatedJournalEntrySummary>(`/api/reconciliation/unmatched/${txnId}/create-entry`, { method: "POST" });
      setCreatedEntry(entry);
      setError(null);
      await refresh();
      if (createdFrom?.id === txnId) {
        setSelected(createdFrom);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create entry.");
    } finally { setCreating(null); }
  };

  const createAllEntries = async () => {
    setCreatingAll(true);
    setConfirmCreateAllOpen(false);
    setBatchCreatedCount(null);
    try {
      const result = await apiFetch<BatchCreateEntriesResponse>("/api/reconciliation/unmatched/batch-create", {
        method: "POST",
        body: JSON.stringify({ all: true }),
      });
      setBatchCreatedCount(result.created_count);
      setCreatedEntry(null);
      setError(null);
      await refresh();
    } catch (err) {
      setBatchCreatedCount(null);
      setError(err instanceof Error ? err.message : "Failed to create entries in bulk.");
    } finally {
      setCreatingAll(false);
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
      saveFlaggedToStorage(next);
      return next;
    });
  };

  const removeFromList = (txnId: string) => {
    setItems((prev) => prev.filter((i) => i.id !== txnId));
    if (selected?.id === txnId) {
      setSelected(null);
    }
  };

  const formatTxnAmount = (item: BankStatementTransactionSummary) =>
    formatCurrencyLocale(item.amount, item.currency || "SGD");

  const formatCreatedEntryAmount = (entry: CreatedJournalEntrySummary) =>
    formatCurrencyLocale(entry.total_amount, entry.currency || selected?.currency || "SGD");

  const summary = useMemo(() => ({ total: items.length, flagged: flagged.size }), [flagged.size, items.length]);
  const aiPrompt = useMemo(() => {
    if (!selected) return null;
    const { description, txn_date, amount, direction } = selected;
    return encodeURIComponent(
      `Help me interpret this transaction: ${description} on ${txn_date}, amount ${amount} (${direction === "IN" ? "inflow" : "outflow"}). Why might it be unmatched?`,
    );
  }, [selected]);

  return (
    <div className="p-6">
      <div className="mb-4">
        <BackLink>Back to Notifications</BackLink>
      </div>
      <div className="page-header flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Unmatched Transactions</h1>
          <p className="page-description">Triage unmatched transactions and create manual journal entries</p>
          <p className="mt-1 text-xs text-muted">Flags and hidden rows are local workspace triage only.</p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/reconciliation" className="btn-secondary text-sm">← Workbench</Link>
          <button
            type="button"
            onClick={() => setConfirmCreateAllOpen(true)}
            disabled={creatingAll || items.length === 0}
            className="btn-primary text-sm"
          >
            {creatingAll ? "Creating..." : "Create All Entries"}
          </button>
          <span className="badge badge-warning">{summary.total} unmatched · {summary.flagged} flagged</span>
        </div>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}
      {batchCreatedCount !== null && (
        <div className="mb-4 p-3 rounded-md bg-[var(--success-muted)] border border-[var(--success)]/30 text-sm">
          Created {batchCreatedCount} journal {batchCreatedCount === 1 ? "entry" : "entries"} from unmatched transactions.
        </div>
      )}

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
                    <div className="font-semibold text-[var(--accent)]">{formatTxnAmount(item)}</div>
                    {flagged.has(item.id) && <span className="badge badge-warning text-[10px]">Flagged locally</span>}
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
                <p className="text-xl font-semibold text-[var(--accent)] mt-1">{formatTxnAmount(selected)}</p>
                {selected.reference && <p className="text-xs text-muted">Ref: {selected.reference}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
                <button onClick={() => createEntry(selected.id)} disabled={creating === selected.id} className="btn-primary">{creating === selected.id ? "Creating..." : "Create Entry"}</button>
                {aiPrompt && <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary">Ask AI</Link>}
                <button onClick={() => toggleFlag(selected.id)} className="btn-secondary">{flagged.has(selected.id) ? "Unflag local" : "Flag local"}</button>
                <button onClick={() => removeFromList(selected.id)} className="btn-secondary">Hide locally</button>
              </div>

              {createdEntry && (
                <div className="p-3 rounded-md bg-[var(--success-muted)] border border-[var(--success)]/30 text-sm">
                  Created entry <strong>{createdEntry.id}</strong> · {formatCreatedEntryAmount(createdEntry)} on {createdEntry.entry_date}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirmCreateAllOpen}
        onCancel={() => !creatingAll && setConfirmCreateAllOpen(false)}
        onConfirm={() => createAllEntries()}
        title="Create All Entries"
        message={`Create draft journal entries for ${items.length} unmatched transaction${items.length === 1 ? "" : "s"}? Review local flags before continuing.`}
        confirmLabel="Create Entries"
        loading={creatingAll}
      />
    </div>
  );
}
