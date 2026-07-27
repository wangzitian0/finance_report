"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BackLink } from "@/components/ui/BackLink";
import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import type { components } from "@/lib/api-types";
import type {
  Account,
  AccountListResponse,
  BankStatementTransactionSummary,
  JournalEntrySummary,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

type EconomicIntent = components["schemas"]["EconomicIntent"];
type ReviewedDispositionPayload =
  components["schemas"]["ReviewedDispositionRequest"];

type ReviewedDispositionDraft = {
  transactionId: string;
  intent: EconomicIntent;
  counterAccountId: string;
  category: string;
  rationale: string;
};

const FLAGGED_STORAGE_KEY = "finance-unmatched-flagged";

const INTENT_OPTIONS: ReadonlyArray<{ value: EconomicIntent; label: string }> =
  [
    { value: "income", label: "Income" },
    { value: "expense", label: "Expense" },
    { value: "expense_refund", label: "Expense refund" },
    { value: "investment_purchase", label: "Investment purchase" },
    { value: "investment_sale", label: "Investment sale" },
    { value: "loan_principal", label: "Loan principal" },
    { value: "loan_interest", label: "Loan interest" },
    { value: "card_repayment", label: "Card repayment" },
    { value: "transfer", label: "Internal transfer" },
    { value: "unknown", label: "Unknown - needs review" },
  ];

function newReviewedDispositionDraft(
  transaction: BankStatementTransactionSummary,
): ReviewedDispositionDraft {
  return {
    transactionId: transaction.id,
    intent: transaction.direction === "IN" ? "income" : "expense",
    counterAccountId: "",
    category: "",
    rationale: "",
  };
}

export function compatibleAccountTypes(
  intent: EconomicIntent,
): Account["type"][] {
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
    case "unknown":
      return [];
  }
}

function needsCategory(intent: EconomicIntent): boolean {
  return ["income", "expense", "expense_refund", "loan_interest"].includes(
    intent,
  );
}

export function isReviewedDispositionComplete(
  intent: EconomicIntent,
  counterAccountId: string,
  category: string,
  rationale: string,
): boolean {
  return Boolean(
    counterAccountId &&
    rationale.trim() &&
    intent !== "transfer" &&
    intent !== "unknown" &&
    (!needsCategory(intent) || category.trim()),
  );
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
  const [selected, setSelected] =
    useState<BankStatementTransactionSummary | null>(null);
  const [draft, setDraft] = useState<ReviewedDispositionDraft | null>(null);
  const [posting, setPosting] = useState(false);
  const [postedEntry, setPostedEntry] = useState<JournalEntrySummary | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [flagged, setFlagged] = useState<Set<string>>(() =>
    loadFlaggedFromStorage(),
  );

  const refresh = useCallback(async () => {
    try {
      const [transactions, accountResponse] = await Promise.all([
        apiOperation("list_unmatched_reconciliation_unmatched_get"),
        apiOperation("list_accounts_accounts_get", {
          query: { is_active: true, limit: 500 },
        }),
      ]);
      setItems(transactions.items);
      setAccounts(accountResponse.items);
      setSelected((current) =>
        current && transactions.items.some((item) => item.id === current.id)
          ? current
          : (transactions.items[0] ?? null),
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Failed to load unmatched transactions.",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setDraft(null);
      return;
    }
    setDraft((current) => {
      return current?.transactionId === selected.id
        ? current
        : newReviewedDispositionDraft(selected);
    });
    setPostedEntry(null);
  }, [selected]);

  const activeDraft =
    selected && draft?.transactionId === selected.id ? draft : null;

  const updateDraft = (
    changes: Partial<Omit<ReviewedDispositionDraft, "transactionId">>,
  ) => {
    setDraft((current) =>
      current && selected && current.transactionId === selected.id
        ? { ...current, ...changes }
        : current,
    );
  };

  const candidateAccounts = useMemo(() => {
    if (!selected) return [];
    const currency = selected.currency || "SGD";
    const types = activeDraft ? compatibleAccountTypes(activeDraft.intent) : [];
    return accounts.filter(
      (account) =>
        account.currency === currency && types.includes(account.type),
    );
  }, [accounts, activeDraft, selected]);

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
    setItems((previous) =>
      previous.filter((item) => item.id !== transactionId),
    );
    if (selected?.id === transactionId) setSelected(null);
  };

  const submitReviewedDisposition = async () => {
    if (
      !selected ||
      !activeDraft ||
      !isReviewedDispositionComplete(
        activeDraft.intent,
        activeDraft.counterAccountId,
        activeDraft.category,
        activeDraft.rationale,
      )
    )
      return;
    setPosting(true);
    try {
      const payload: ReviewedDispositionPayload = {
        intent: activeDraft.intent,
        counter_account_id: activeDraft.counterAccountId,
        rationale: activeDraft.rationale.trim(),
        ...(needsCategory(activeDraft.intent)
          ? { category: activeDraft.category.trim() }
          : {}),
      };
      const entry = await apiOperation(
        "submit_unmatched_reviewed_disposition_reconciliation_unmatched__txn_id__reviewed_disposition_post",
        { path: { txn_id: selected.id }, body: payload },
      );
      setPostedEntry(entry);
      setError(null);
      await refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Failed to post reviewed disposition.",
      );
    } finally {
      setPosting(false);
    }
  };

  const formatTxnAmount = (item: BankStatementTransactionSummary) =>
    formatCurrencyLocale(item.amount, item.currency || "SGD");
  const summary = useMemo(
    () => ({ total: items.length, flagged: flagged.size }),
    [flagged.size, items.length],
  );
  const aiPrompt = useMemo(() => {
    if (!selected) return null;
    const { description, txn_date, amount, direction } = selected;
    return encodeURIComponent(
      `Help me interpret this transaction: ${description} on ${txn_date}, amount ${amount} (${direction === "IN" ? "inflow" : "outflow"}). Why might it be unmatched?`,
    );
  }, [selected]);
  const canSubmit =
    activeDraft !== null &&
    isReviewedDispositionComplete(
      activeDraft.intent,
      activeDraft.counterAccountId,
      activeDraft.category,
      activeDraft.rationale,
    );

  return (
    <div className="p-6">
      <div className="mb-4">
        <BackLink>Back to Notifications</BackLink>
      </div>
      <div className="page-header flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h1 className="page-title">Unmatched Transactions</h1>
          <p className="page-description">
            Confirm the economic meaning before a source transaction can be
            posted.
          </p>
          <p className="mt-1 text-xs text-muted">
            Flags and hidden rows are local workspace triage only.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/reconciliation" className="btn-secondary text-sm">
            ← Workbench
          </Link>
          <span className="badge badge-warning">
            {summary.total} unmatched · {summary.flagged} flagged
          </span>
        </div>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}
      {postedEntry && (
        <div className="mb-4 p-3 rounded-md bg-[var(--success-muted)] border border-[var(--success)]/30 text-sm">
          Posted reviewed entry <strong>{postedEntry.id}</strong> on{" "}
          {postedEntry.entry_date}.
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
                    <p className="font-medium text-sm truncate">
                      {item.description}
                    </p>
                    <p className="text-xs text-muted">
                      {item.txn_date} · {item.direction === "IN" ? "In" : "Out"}
                    </p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="font-semibold text-[var(--accent)]">
                      {formatTxnAmount(item)}
                    </div>
                    {flagged.has(item.id) && (
                      <span className="badge badge-warning text-[10px]">
                        Flagged locally
                      </span>
                    )}
                  </div>
                </div>
              </button>
            ))}
            {items.length === 0 && (
              <div className="p-8 text-center text-muted text-sm">
                No unmatched transactions
              </div>
            )}
          </div>
        </div>

        <div className="card p-5">
          <h2 className="font-semibold mb-4">Reviewed Disposition</h2>
          {!selected || !activeDraft ? (
            <p className="text-sm text-muted">Select a transaction to review</p>
          ) : (
            <div className="space-y-4">
              <div className="p-3 rounded-md bg-[var(--background-muted)]">
                <p className="font-medium">{selected.description}</p>
                <p className="text-xs text-muted">
                  {selected.txn_date} ·{" "}
                  {selected.direction === "IN" ? "Inflow" : "Outflow"}
                </p>
                <p className="text-xl font-semibold text-[var(--accent)] mt-1">
                  {formatTxnAmount(selected)}
                </p>
                {selected.reference && (
                  <p className="text-xs text-muted">
                    Ref: {selected.reference}
                  </p>
                )}
              </div>

              <label className="block text-sm font-medium">
                Economic intent
                <select
                  className="input mt-1 w-full"
                  value={activeDraft.intent}
                  onChange={(event) =>
                    updateDraft({
                      intent: event.target.value as EconomicIntent,
                      counterAccountId: "",
                    })
                  }
                >
                  {INTENT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              {activeDraft.intent === "transfer" ? (
                <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-3 text-sm">
                  Internal transfers must be paired in the reconciliation
                  workbench; they cannot be posted as income or expense.
                </div>
              ) : activeDraft.intent === "unknown" ? (
                <div className="rounded-md border border-[var(--warning)]/40 bg-[var(--warning-muted)] p-3 text-sm">
                  Unknown economic intent must be resolved from source evidence
                  before it can be posted.
                </div>
              ) : (
                <>
                  <label className="block text-sm font-medium">
                    Counter account
                    <select
                      className="input mt-1 w-full"
                      value={activeDraft.counterAccountId}
                      onChange={(event) =>
                        updateDraft({ counterAccountId: event.target.value })
                      }
                    >
                      <option value="">Choose a compatible account</option>
                      {candidateAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.name} · {account.type}
                        </option>
                      ))}
                    </select>
                  </label>
                  {candidateAccounts.length === 0 && (
                    <p className="text-xs text-muted">
                      Create an active{" "}
                      {compatibleAccountTypes(activeDraft.intent).join("/")}{" "}
                      account in {selected.currency || "SGD"} before posting.
                    </p>
                  )}
                  {needsCategory(activeDraft.intent) && (
                    <label className="block text-sm font-medium">
                      Report category
                      <input
                        className="input mt-1 w-full"
                        value={activeDraft.category}
                        onChange={(event) =>
                          updateDraft({ category: event.target.value })
                        }
                        maxLength={100}
                        placeholder="For example, DINING or SALARY"
                      />
                    </label>
                  )}
                  <label className="block text-sm font-medium">
                    Review rationale
                    <textarea
                      className="input mt-1 w-full min-h-20"
                      value={activeDraft.rationale}
                      onChange={(event) =>
                        updateDraft({ rationale: event.target.value })
                      }
                      maxLength={500}
                      placeholder="What source evidence supports this decision?"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void submitReviewedDisposition()}
                    disabled={posting || !canSubmit}
                    className="btn-primary"
                  >
                    {posting ? "Posting reviewed entry..." : "Confirm and Post"}
                  </button>
                </>
              )}

              <div className="flex flex-wrap gap-2">
                {aiPrompt && (
                  <Link
                    href={`/chat?prompt=${aiPrompt}`}
                    className="btn-secondary"
                  >
                    Ask AI
                  </Link>
                )}
                <button
                  onClick={() => toggleFlag(selected.id)}
                  className="btn-secondary"
                >
                  {flagged.has(selected.id) ? "Unflag local" : "Flag local"}
                </button>
                <button
                  onClick={() => removeFromList(selected.id)}
                  className="btn-secondary"
                >
                  Hide locally
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
