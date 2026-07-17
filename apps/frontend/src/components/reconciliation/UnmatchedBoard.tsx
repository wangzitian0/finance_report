"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BackLink } from "@/components/ui/BackLink";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/audit/money";
import type {
  Account,
  AccountListResponse,
  BankStatementTransactionSummary,
  JournalEntrySummary,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

type EconomicIntent =
  | "income"
  | "expense"
  | "expense_refund"
  | "investment_purchase"
  | "investment_sale"
  | "loan_principal"
  | "loan_interest"
  | "card_repayment"
  | "transfer";

type ReviewedDispositionPayload = {
  intent: EconomicIntent;
  counter_account_id: string;
  category?: string;
  rationale: string;
};

const FLAGGED_STORAGE_KEY = "finance-unmatched-flagged";

const INTENT_OPTIONS: ReadonlyArray<{ value: EconomicIntent; label: string }> = [
  { value: "income", label: "Income" },
  { value: "expense", label: "Expense" },
  { value: "expense_refund", label: "Expense refund" },
  { value: "investment_purchase", label: "Investment purchase" },
  { value: "investment_sale", label: "Investment sale" },
  { value: "loan_principal", label: "Loan principal" },
  { value: "loan_interest", label: "Loan interest" },
  { value: "card_repayment", label: "Card repayment" },
  { value: "transfer", label: "Internal transfer" },
];

function compatibleAccountTypes(intent: EconomicIntent): Account["type"][] {
  switch (intent) {
    case "income":
      return ["INCOME"];
    case "expense":
    case "expense_refund":
    case "loan_interest":
      return ["EXPENSE"];
    case "investment_purchase":
    case "investment_sale":
    case "transfer":
      return ["ASSET"];
    case "loan_principal":
    case "card_repayment":
      return ["LIABILITY"];
  }
}

function needsCategory(intent: EconomicIntent): boolean {
  return ["income", "expense", "expense_refund", "loan_interest"].includes(intent);
}

function loadFlaggedFromStorage(): Set<string> {
  try {
    if (typeof window === "undefined") return new Set();
    const stored = localStorage.getItem(FLAGGED_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) return new Set(parsed);
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
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState<BankStatementTransactionSummary | null>(null);
  const [intent, setIntent] = useState<EconomicIntent>("expense");
  const [counterAccountId, setCounterAccountId] = useState("");
  const [category, setCategory] = useState("");
  const [rationale, setRationale] = useState("");
  const [posting, setPosting] = useState(false);
  const [postedEntry, setPostedEntry] = useState<JournalEntrySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<Set<string>>(() => loadFlaggedFromStorage());

  const refresh = useCallback(async () => {
    try {
      const [transactions, accountResponse] = await Promise.all([
        apiFetch<UnmatchedTransactionsResponse>("/api/reconciliation/unmatched"),
        apiFetch<AccountListResponse>("/api/accounts?is_active=true&limit=500"),
      ]);
      setItems(transactions.items);
      setAccounts(accountResponse.items);
      setSelected((current) =>
        current && transactions.items.some((item) => item.id === current.id)
          ? current
          : transactions.items[0] ?? null,
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to load unmatched transactions.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    setIntent(selected.direction === "IN" ? "income" : "expense");
    setCounterAccountId("");
    setCategory("");
    setRationale("");
    setPostedEntry(null);
  }, [selected]);

  const candidateAccounts = useMemo(() => {
    if (!selected) return [];
    const currency = selected.currency || "SGD";
    const types = compatibleAccountTypes(intent);
    return accounts.filter((account) => account.currency === currency && types.includes(account.type));
  }, [accounts, intent, selected]);

  const toggleFlag = (transactionId: string) => {
    setFlagged((previous) => {
      const next = new Set(previous);
      if (next.has(transactionId)) next.delete(transactionId);
      else next.add(transactionId);
      saveFlaggedToStorage(next);
      return next;
    });
  };

  const removeFromList = (transactionId: string) => {
    setItems((previous) => previous.filter((item) => item.id !== transactionId));
    if (selected?.id === transactionId) setSelected(null);
  };

  const submitReviewedDisposition = async () => {
    if (!selected || !counterAccountId || !rationale.trim() || intent === "transfer") return;
    setPosting(true);
    try {
      const payload: ReviewedDispositionPayload = {
        intent,
        counter_account_id: counterAccountId,
        rationale: rationale.trim(),
        ...(needsCategory(intent) ? { category: category.trim() } : {}),
      };
      const entry = await apiFetch<JournalEntrySummary>(
        `/api/reconciliation/unmatched/${selected.id}/reviewed-disposition`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      setPostedEntry(entry);
      setError(null);
      await refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to post reviewed disposition.");
    } finally {
      setPosting(false);
    }
  };

  const formatTxnAmount = (item: BankStatementTransactionSummary) =>
    formatCurrencyLocale(item.amount, item.currency || "SGD");
  const summary = useMemo(() => ({ total: items.length, flagged: flagged.size }), [flagged.size, items.length]);
  const aiPrompt = useMemo(() => {
    if (!selected) return null;
    const { description, txn_date, amount, direction } = selected;
    return encodeURIComponent(
      `Help me interpret this transaction: ${description} on ${txn_date}, amount ${amount} (${direction === "IN" ? "inflow" : "outflow"}). Why might it be unmatched?`,
    );
  }, [selected]);
  const canSubmit = Boolean(
    selected && counterAccountId && rationale.trim() && intent !== "transfer" && (!needsCategory(intent) || category.trim()),
  );

  return (
    <div className="p-6">
      <div className="mb-4"><BackLink>Back to Notifications</BackLink></div>
      <div className="page-header flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Unmatched Transactions</h1>
          <p className="page-description">Confirm the economic meaning before a source transaction can be posted.</p>
          <p className="mt-1 text-xs text-muted">Flags and hidden rows are local workspace triage only.</p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/reconciliation" className="btn-secondary text-sm">← Workbench</Link>
          <span className="badge badge-warning">{summary.total} unmatched · {summary.flagged} flagged</span>
        </div>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}
      {postedEntry && (
        <div className="mb-4 p-3 rounded-md bg-[var(--success-muted)] border border-[var(--success)]/30 text-sm">
          Posted reviewed entry <strong>{postedEntry.id}</strong> on {postedEntry.entry_date}.
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
          <h2 className="font-semibold mb-4">Reviewed Disposition</h2>
          {!selected ? <p className="text-sm text-muted">Select a transaction to review</p> : (
            <div className="space-y-4">
              <div className="p-3 rounded-md bg-[var(--background-muted)]">
                <p className="font-medium">{selected.description}</p>
                <p className="text-xs text-muted">{selected.txn_date} · {selected.direction === "IN" ? "Inflow" : "Outflow"}</p>
                <p className="text-xl font-semibold text-[var(--accent)] mt-1">{formatTxnAmount(selected)}</p>
                {selected.reference && <p className="text-xs text-muted">Ref: {selected.reference}</p>}
              </div>

              <label className="block text-sm font-medium">
                Economic intent
                <select className="input mt-1 w-full" value={intent} onChange={(event) => { setIntent(event.target.value as EconomicIntent); setCounterAccountId(""); }}>
                  {INTENT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>

              {intent === "transfer" ? (
                <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-3 text-sm">
                  Internal transfers must be paired in the reconciliation workbench; they cannot be posted as income or expense.
                </div>
              ) : (
                <>
                  <label className="block text-sm font-medium">
                    Counter account
                    <select className="input mt-1 w-full" value={counterAccountId} onChange={(event) => setCounterAccountId(event.target.value)}>
                      <option value="">Choose a compatible account</option>
                      {candidateAccounts.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.type}</option>)}
                    </select>
                  </label>
                  {candidateAccounts.length === 0 && <p className="text-xs text-muted">Create an active {compatibleAccountTypes(intent).join("/")} account in {selected.currency || "SGD"} before posting.</p>}
                  {needsCategory(intent) && (
                    <label className="block text-sm font-medium">
                      Report category
                      <input className="input mt-1 w-full" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={100} placeholder="For example, DINING or SALARY" />
                    </label>
                  )}
                  <label className="block text-sm font-medium">
                    Review rationale
                    <textarea className="input mt-1 w-full min-h-20" value={rationale} onChange={(event) => setRationale(event.target.value)} maxLength={500} placeholder="What source evidence supports this decision?" />
                  </label>
                  <button type="button" onClick={() => void submitReviewedDisposition()} disabled={posting || !canSubmit} className="btn-primary">
                    {posting ? "Posting reviewed entry..." : "Confirm and Post"}
                  </button>
                </>
              )}

              <div className="flex flex-wrap gap-2">
                {aiPrompt && <Link href={`/chat?prompt=${aiPrompt}`} className="btn-secondary">Ask AI</Link>}
                <button onClick={() => toggleFlag(selected.id)} className="btn-secondary">{flagged.has(selected.id) ? "Unflag local" : "Flag local"}</button>
                <button onClick={() => removeFromList(selected.id)} className="btn-secondary">Hide locally</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
