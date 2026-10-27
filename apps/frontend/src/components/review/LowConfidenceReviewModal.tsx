"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquareText, Check } from "lucide-react";

import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatCategoryLabel, getCategoriesForDirection } from "@/lib/categories";
import DetailDialog from "@/components/ui/DetailDialog";
import { useToast } from "@/components/ui/Toast";
import { RowConfidenceBadge } from "@/components/review/RowConfidenceBadge";
import { PENDING_CHAT_PROMPT_KEY } from "@/lib/chatStorage";
import type { BankStatementTransaction } from "@/lib/types";

export interface LowConfidenceReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  transaction: BankStatementTransaction | null;
  currency?: string;
  onSuccess?: () => void;
}

export function LowConfidenceReviewModal({ isOpen, onClose, transaction, currency = "SGD", onSuccess }: LowConfidenceReviewModalProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const [category, setCategory] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const categorySelectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (isOpen && transaction) {
      const initialCat = String(transaction.proposed_category ?? transaction.category ?? "").trim();
      const available = getCategoriesForDirection(transaction.direction);
      const matched = available.find((opt) => opt.value === initialCat.toUpperCase() || opt.label.toLowerCase() === initialCat.toLowerCase());
      setCategory(matched ? matched.value : initialCat);
      setError(null);
      setSaving(false);
      setTimeout(() => categorySelectRef.current?.focus(), 50);
    }
  }, [isOpen, transaction]);

  if (!isOpen || !transaction) return null;

  const availableCategories = getCategoriesForDirection(transaction.direction);
  const isPositive = transaction.direction === "IN";
  const displayCurrency = transaction.currency || currency;
  const chatPrompt = `Please analyze this transaction: '${transaction.description}', amount: ${transaction.amount} ${displayCurrency} (${isPositive ? "Income" : "Expense"}) on ${transaction.txn_date}. What is the recommended accounting category and should it be considered a personal or business expense?`;

  const handleSave = async (e?: React.FormEvent | React.MouseEvent) => {
    e?.preventDefault();
    if (saving) return;
    const trimmed = category.trim();
    if (!trimmed) { setError("Please select or enter a category."); return; }
    setSaving(true);
    setError(null);
    try {
      await apiOperation("create_correction_corrections_post", { body: { transaction_id: transaction.id, corrected_category: trimmed } });
      showToast(`Category updated to "${formatCategoryLabel(trimmed)}"`, "success");
      onSuccess?.();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to record correction.";
      setError(msg);
      showToast(msg, "error");
    } finally {
      setSaving(false);
    }
  };

  // DetailDialog closes on Escape, backdrop and the X button: none of them may interrupt a save.
  const handleClose = () => { if (!saving) onClose(); };

  const handleAskAi = () => {
    try { sessionStorage.setItem(PENDING_CHAT_PROMPT_KEY, chatPrompt); } catch { /* ignore */ }
    router.push("/chat");
  };

  return (
    <DetailDialog isOpen onClose={handleClose} title="Review Low-Confidence Transaction">
      <p className="text-xs text-muted">Confirm or adjust the extracted economic classification</p>
      <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background-muted)]/40 p-3.5 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1"><p className="text-xs text-muted">Description</p><p className="font-medium text-sm break-words">{transaction.description}</p></div>
          <div className="text-right flex-shrink-0"><p className="text-xs text-muted">Amount</p><p className={`text-sm font-semibold tabular-nums ${isPositive ? "text-[var(--success)]" : "text-[var(--error)]"}`}>{isPositive ? "+" : "-"}{formatCurrencyLocale(transaction.amount, displayCurrency)}</p></div>
        </div>
        <div className="flex items-center justify-between gap-2 pt-1 border-t border-[var(--border)]/60 text-xs">
          <span className="text-muted">Date: {transaction.txn_date}</span>
          <div className="flex items-center gap-1.5"><span className="text-muted">Confidence:</span><RowConfidenceBadge txn={transaction} /></div>
        </div>
      </div>
      <form onSubmit={handleSave} className="mt-4 space-y-4">
        <div>
          <label htmlFor="corrected-category-input" className="block text-xs font-semibold uppercase text-muted mb-1.5">Classification Category</label>
          <select id="corrected-category-input" ref={categorySelectRef} className="input w-full text-sm" value={category} onChange={(e) => { setCategory(e.target.value); setError(null); }} disabled={saving}>
            <option value="">Select a category...</option>
            {availableCategories.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
          {error && <p role="alert" className="mt-1 text-xs text-[var(--error)]">{error}</p>}
        </div>
        <div>
          <p className="text-xs text-muted mb-1.5">Suggested categories:</p>
          <div className="flex flex-wrap gap-1.5">
            {availableCategories.map((opt) => {
              const isSelected = category.trim().toUpperCase() === opt.value || category.trim().toLowerCase() === opt.label.toLowerCase();
              return (<button key={opt.value} type="button" onClick={() => { setCategory(opt.value); setError(null); }} className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${isSelected ? "bg-[var(--accent)] text-white" : "bg-[var(--background-muted)] text-[var(--foreground)] hover:bg-[var(--border)]"}`}>{opt.label}</button>);
            })}
          </div>
        </div>
        <div className="flex flex-col gap-2 pt-3 sm:flex-row sm:items-center sm:justify-between border-t border-[var(--border)]">
          <button type="button" onClick={handleAskAi} className="btn-ghost text-xs flex items-center justify-center gap-1.5 text-[var(--accent)] hover:bg-[var(--accent)]/10" title="Open AI Chat Assistant with this transaction context"><MessageSquareText className="h-3.5 w-3.5" /><span>Ask AI Assistant</span></button>
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} disabled={saving} className="btn-secondary text-xs px-3 py-1.5">Cancel</button>
            <button type="submit" onClick={handleSave} disabled={saving || !category.trim()} className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5 disabled:opacity-50">
              {saving ? (<><span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" /><span>Saving...</span></>) : (<><Check className="h-3.5 w-3.5" /><span>Save Correction</span></>)}
            </button>
          </div>
        </div>
      </form>
    </DetailDialog>
  );
}
