"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useFocusTrap } from "@/hooks/useFocusTrap";
import { apiFetch } from "@/lib/api";
import { Account } from "@/lib/types";

interface OpeningBalanceModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
    accounts: Account[];
}

/** Two decimal places, positive — mirrors the backend `balances` validator (#949). */
const AMOUNT_RE = /^\d+(\.\d{1,2})?$/;

function defaultEntryDate(): string {
    // Opening balances are normally recorded at the start of the first year the
    // user has data for; default to Jan 1 of the current year as a safe nudge.
    const now = new Date();
    return `${now.getFullYear()}-01-01`;
}

/**
 * Guided opening-balance flow (#949 / AC2.15.8).
 *
 * Lets a non-accountant establish starting balances by entering what each
 * account was worth on a start date. The backend posts the balanced journal
 * entry (offsetting into Opening Balance Equity), so the user never hand-writes
 * double-entry lines and the cross-year balance sheet is complete from day one.
 */
export default function OpeningBalanceModal({ isOpen, onClose, onSuccess, accounts }: OpeningBalanceModalProps) {
    const dialogRef = useRef<HTMLDivElement>(null);
    useFocusTrap(dialogRef, isOpen);

    const [entryDate, setEntryDate] = useState(defaultEntryDate);
    const [memo, setMemo] = useState("Opening balances");
    const [amounts, setAmounts] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    // Only real (non-system) accounts can carry an opening balance.
    const eligibleAccounts = useMemo(
        () => accounts.filter((a) => a.is_active && a.type !== "INCOME" && a.type !== "EXPENSE"),
        [accounts],
    );

    useEffect(() => {
        if (isOpen) {
            setEntryDate(defaultEntryDate());
            setMemo("Opening balances");
            setAmounts({});
            setError(null);
            setSubmitting(false);
        }
    }, [isOpen]);

    if (!isOpen) return null;

    const filledEntries = Object.entries(amounts).filter(([, value]) => value.trim() !== "");

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setError(null);

        if (filledEntries.length === 0) {
            setError("Enter a starting balance for at least one account.");
            return;
        }
        const invalid = filledEntries.find(([, value]) => !AMOUNT_RE.test(value.trim()) || Number(value) <= 0);
        if (invalid) {
            setError("Balances must be positive amounts with at most two decimal places.");
            return;
        }

        const balances = Object.fromEntries(filledEntries.map(([id, value]) => [id, value.trim()]));

        setSubmitting(true);
        try {
            await apiFetch("/api/accounts/opening-balances", {
                method: "POST",
                body: JSON.stringify({ entry_date: entryDate, balances, memo: memo.trim() || "Opening balances" }),
            });
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to record opening balances");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="fixed inset-0 bg-black/60" onClick={onClose} />
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-label="Set opening balances"
                className="relative z-10 flex max-h-[90vh] w-full max-w-lg flex-col card animate-slide-up"
            >
                <div className="card-header">
                    <h2 className="text-lg font-semibold">Set opening balances</h2>
                </div>

                <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
                    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-6">
                        <p className="text-sm text-muted">
                            Tell us what each account was worth on your start date. We&apos;ll record the bookkeeping
                            entry for you, so your reports are complete from day one — no journal entries required.
                        </p>

                        <div>
                            <label htmlFor="opening-balance-date" className="mb-1.5 block text-sm font-medium">
                                As-of date *
                            </label>
                            <input
                                id="opening-balance-date"
                                type="date"
                                value={entryDate}
                                onChange={(e) => setEntryDate(e.target.value)}
                                className="input"
                            />
                            <p className="mt-1 text-xs text-muted">
                                The day before your first imported transactions (usually the start of the year).
                            </p>
                        </div>

                        {eligibleAccounts.length === 0 ? (
                            <div className="alert-error">
                                Create an asset, liability, or equity account first, then set its opening balance.
                            </div>
                        ) : (
                            <div className="space-y-2">
                                <span className="block text-sm font-medium">Starting balances</span>
                                {eligibleAccounts.map((account) => (
                                    <div key={account.id} className="flex items-center gap-3">
                                        <label
                                            htmlFor={`opening-balance-${account.id}`}
                                            className="min-w-0 flex-1 truncate text-sm"
                                        >
                                            {account.name}
                                            <span className="ml-1 text-xs text-muted">{account.currency}</span>
                                        </label>
                                        <input
                                            id={`opening-balance-${account.id}`}
                                            type="text"
                                            inputMode="decimal"
                                            placeholder="0.00"
                                            value={amounts[account.id] ?? ""}
                                            onChange={(e) =>
                                                setAmounts((prev) => ({ ...prev, [account.id]: e.target.value }))
                                            }
                                            aria-label={`Opening balance for ${account.name}`}
                                            className="input w-32 text-right"
                                        />
                                    </div>
                                ))}
                            </div>
                        )}

                        <div>
                            <label htmlFor="opening-balance-memo" className="mb-1.5 block text-sm font-medium">
                                Memo
                            </label>
                            <input
                                id="opening-balance-memo"
                                type="text"
                                value={memo}
                                onChange={(e) => setMemo(e.target.value)}
                                className="input"
                            />
                        </div>

                        {error && <div className="alert-error">{error}</div>}
                    </div>

                    <div className="flex gap-3 border-t border-[var(--border)] p-6 pt-4">
                        <button type="button" onClick={onClose} className="btn-secondary flex-1">
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={submitting || eligibleAccounts.length === 0}
                            className="btn-primary flex-1"
                        >
                            {submitting ? "Saving..." : "Record opening balances"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
