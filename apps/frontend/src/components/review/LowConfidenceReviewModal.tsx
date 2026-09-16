"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { MessageSquareText, AlertTriangle, Check, X } from "lucide-react";

import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { useToast } from "@/components/ui/Toast";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import type { BankStatementTransaction } from "@/lib/types";

export interface LowConfidenceReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  transaction: BankStatementTransaction | null;
  currency?: string;
  onSuccess?: () => void;
}

const QUICK_CATEGORIES = [
  "Dining",
  "Groceries",
  "Transport",
  "Utilities",
  "Salary",
  "Shopping",
  "Entertainment",
  "Healthcare",
  "Transfer",
];

export function LowConfidenceReviewModal({
  isOpen,
  onClose,
  transaction,
  currency = "SGD",
  onSuccess,
}: LowConfidenceReviewModalProps) {
  const { showToast } = useToast();
  const [category, setCategory] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const categoryInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && transaction) {
      setCategory("");
      setError(null);
      setSaving(false);
      setTimeout(() => {
        categoryInputRef.current?.focus();
      }, 50);
    }
  }, [isOpen, transaction]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, saving]);

  if (!isOpen || !transaction) {
    return null;
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = category.trim();
    if (!trimmed) {
      setError("Please select or enter a category.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await apiOperation("create_correction_corrections_post", {
        body: {
          transaction_id: transaction.id,
          corrected_category: trimmed,
        },
      });
      showToast(`Category updated to "${trimmed}"`, "success");
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

  const isPositive = transaction.direction === "IN";
  const displayCurrency = transaction.currency || currency;
  const chatPrompt = `Please analyze this transaction: '${transaction.description}', amount: ${transaction.amount} ${displayCurrency} (${isPositive ? "Income" : "Expense"}) on ${transaction.txn_date}. What is the recommended accounting category and should it be considered a personal or business expense?`;
  const chatHref = `/chat?prompt=${encodeURIComponent(chatPrompt)}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 animate-fade-in backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="low-confidence-modal-title"
    >
      <div
        ref={dialogRef}
        className="card w-full max-w-lg border border-[var(--border)] bg-[var(--background)] p-6 shadow-2xl animate-scale-up"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] pb-4">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--warning-muted)] text-[var(--warning)]">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div>
              <h2 id="low-confidence-modal-title" className="text-base font-semibold">
                Review Low-Confidence Transaction
              </h2>
              <p className="text-xs text-muted">
                Confirm or adjust the extracted economic classification
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-md p-1 text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)] disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Transaction Summary Card */}
        <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background-muted)]/40 p-3.5 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted">Description</p>
              <p className="font-medium text-sm break-words">{transaction.description}</p>
            </div>
            <div className="text-right flex-shrink-0">
              <p className="text-xs text-muted">Amount</p>
              <p
                className={`text-sm font-semibold tabular-nums ${
                  isPositive ? "text-[var(--success)]" : "text-[var(--error)]"
                }`}
              >
                {isPositive ? "+" : "-"}
                {formatCurrencyLocale(transaction.amount, displayCurrency)}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 pt-1 border-t border-[var(--border)]/60 text-xs">
            <span className="text-muted">Date: {transaction.txn_date}</span>
            <div className="flex items-center gap-1.5">
              <span className="text-muted">Confidence:</span>
              {transaction.confidence_tier ? (
                <ConfidenceBadge tier={transaction.confidence_tier} />
              ) : (
                <span className="badge badge-warning">{transaction.confidence ?? "low"}</span>
              )}
            </div>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSave} className="mt-4 space-y-4">
          <div>
            <label htmlFor="corrected-category-input" className="block text-xs font-semibold uppercase text-muted mb-1.5">
              Classification Category <span className="text-[var(--error)]">*</span>
            </label>
            <input
              id="corrected-category-input"
              ref={categoryInputRef}
              type="text"
              className="input w-full text-sm"
              placeholder="e.g. Dining, Utilities, Software..."
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                if (error) setError(null);
              }}
              disabled={saving}
            />
            {error && (
              <p role="alert" className="mt-1 text-xs text-[var(--error)]">
                {error}
              </p>
            )}
          </div>

          {/* Quick Category Chips */}
          <div>
            <p className="text-xs text-muted mb-1.5">Suggested categories:</p>
            <div className="flex flex-wrap gap-1.5">
              {QUICK_CATEGORIES.map((cat) => {
                const isSelected = category.toLowerCase() === cat.toLowerCase();
                return (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => {
                      setCategory(cat);
                      if (error) setError(null);
                    }}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
                      isSelected
                        ? "bg-[var(--accent)] text-white"
                        : "bg-[var(--background-muted)] text-[var(--foreground)] hover:bg-[var(--border)]"
                    }`}
                  >
                    {cat}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Action Row */}
          <div className="flex flex-col gap-2 pt-3 sm:flex-row sm:items-center sm:justify-between border-t border-[var(--border)]">
            <Link
              href={chatHref}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost text-xs flex items-center justify-center gap-1.5 text-[var(--accent)] hover:bg-[var(--accent)]/10"
              title="Open AI Chat Assistant with this transaction context"
            >
              <MessageSquareText className="h-3.5 w-3.5" />
              <span>Ask AI Assistant</span>
            </Link>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="btn-secondary text-xs px-3 py-1.5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || !category.trim()}
                className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5 disabled:opacity-50"
              >
                {saving ? (
                  <>
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    <span>Save Correction</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
