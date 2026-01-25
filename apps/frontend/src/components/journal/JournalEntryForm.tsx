"use client";

import { useEffect, useState } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { apiFetch } from "@/lib/api";
import { formatAmount, isAmountZero, parseAmount, sumAmounts } from "@/lib/currency";
import { Account, JournalEntry } from "@/lib/types";

interface JournalEntryFormProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

const journalLineSchema = z.object({
    account_id: z.string().min(1, "Account is required"),
    direction: z.enum(["DEBIT", "CREDIT"]),
    amount: z.string().min(1, "Amount is required"),
    currency: z.string(),
});

const journalEntrySchema = z.object({
    entry_date: z.string().min(1, "Date is required"),
    memo: z.string().min(1, "Memo is required").trim(),
    lines: z.array(journalLineSchema).min(2, "At least 2 lines are required"),
}).refine((data) => {
    const totalDebits = sumAmounts(
        data.lines.filter((l) => l.direction === "DEBIT" && l.amount).map((l) => parseAmount(l.amount))
    );
    const totalCredits = sumAmounts(
        data.lines.filter((l) => l.direction === "CREDIT" && l.amount).map((l) => parseAmount(l.amount))
    );
    return isAmountZero(totalDebits.minus(totalCredits), 0.01);
}, {
    message: "Entry must be balanced (Debits = Credits)",
    path: ["lines"],
});

type JournalEntryForm = z.infer<typeof journalEntrySchema>;

export default function JournalEntryForm({ isOpen, onClose, onSuccess }: JournalEntryFormProps) {
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [postImmediately, setPostImmediately] = useState(false);

    const {
        register,
        handleSubmit,
        control,
        watch,
        reset,
        formState: { errors, isSubmitting },
    } = useForm<JournalEntryForm>({
        resolver: zodResolver(journalEntrySchema),
        defaultValues: {
            entry_date: new Date().toISOString().split("T")[0],
            memo: "",
            lines: [
                { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" },
                { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" },
            ],
        },
    });

    const { fields, append, remove } = useFieldArray({
        control,
        name: "lines",
    });

    const lines = watch("lines");

    useEffect(() => {
        if (isOpen) {
            apiFetch<{ items: Account[] }>("/api/accounts")
                .then((data) => setAccounts(data.items))
                .catch(() => setAccounts([]));
        }
    }, [isOpen]);

    const totalDebits = sumAmounts(
        lines.filter((l) => l.direction === "DEBIT" && l.amount).map((l) => parseAmount(l.amount))
    );
    const totalCredits = sumAmounts(
        lines.filter((l) => l.direction === "CREDIT" && l.amount).map((l) => parseAmount(l.amount))
    );
    const isBalanced = isAmountZero(totalDebits.minus(totalCredits), 0.01);

    const onSubmit = async (data: JournalEntryForm) => {
        setError(null);

        try {
            const createdEntry = await apiFetch<JournalEntry>("/api/journal-entries", {
                method: "POST",
                body: JSON.stringify({
                    entry_date: data.entry_date,
                    memo: data.memo,
                    source_type: "manual",
                    lines: data.lines.map((l) => ({
                        account_id: l.account_id,
                        direction: l.direction,
                        amount: formatAmount(l.amount, 2),
                        currency: l.currency,
                    })),
                }),
            });

            if (postImmediately) {
                await apiFetch(`/api/journal-entries/${createdEntry.id}/post`, {
                    method: "POST",
                });
            }

            reset({
                entry_date: new Date().toISOString().slice(0, 10),
                memo: "",
                lines: [
                    { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" },
                    { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" },
                ],
            });
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to create entry");
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4">
            <div className="fixed inset-0 bg-black/60" onClick={onClose} />
            <div className="relative z-10 w-full max-w-2xl card animate-slide-up my-8">
                <div className="card-header">
                    <h2 className="text-lg font-semibold">New Journal Entry</h2>
                    <p className="text-sm text-muted">Create a balanced double-entry transaction</p>
                </div>

                <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Date *</label>
                            <input type="date" {...register("entry_date")} className="input" />
                            {errors.entry_date && (
                                <p className="text-sm text-red-500 mt-1">{errors.entry_date.message}</p>
                            )}
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Memo *</label>
                            <input type="text" {...register("memo")} placeholder="Description" className="input" />
                            {errors.memo && (
                                <p className="text-sm text-red-500 mt-1">{errors.memo.message}</p>
                            )}
                        </div>
                    </div>

                    <div>
                        <div className="flex items-center justify-between mb-3">
                            <label className="text-sm font-medium">Journal Lines</label>
                            <button
                                type="button"
                                onClick={() =>
                                    append({ account_id: "", direction: "DEBIT", amount: "", currency: "SGD" })
                                }
                                className="text-sm text-[var(--accent)] hover:underline"
                            >
                                + Add Line
                            </button>
                        </div>
                        <div className="space-y-2">
                            {fields.map((field, index) => (
                                <div key={field.id} className="flex gap-2 items-center">
                                    <select
                                        {...register(`lines.${index}.account_id`)}
                                        className="input flex-1 text-sm"
                                    >
                                        <option value="">Select Account</option>
                                        {accounts.map((acc) => (
                                            <option key={acc.id} value={acc.id}>
                                                {acc.code ? `${acc.code} - ` : ""}
                                                {acc.name}
                                            </option>
                                        ))}
                                    </select>
                                    <select
                                        {...register(`lines.${index}.direction`)}
                                        className={`input w-24 text-sm ${lines[index]?.direction === "DEBIT"
                                                ? "text-[var(--info)]"
                                                : "text-[var(--success)]"
                                            }`}
                                    >
                                        <option value="DEBIT">Debit</option>
                                        <option value="CREDIT">Credit</option>
                                    </select>
                                    <input
                                        type="number"
                                        step="0.01"
                                        min="0"
                                        {...register(`lines.${index}.amount`)}
                                        placeholder="0.00"
                                        className="input w-28 text-sm text-right"
                                    />
                                    {fields.length > 2 && (
                                        <button
                                            type="button"
                                            onClick={() => remove(index)}
                                            className="btn-ghost p-2 text-muted hover:text-[var(--error)]"
                                        >
                                            <svg
                                                className="w-4 h-4"
                                                fill="none"
                                                stroke="currentColor"
                                                viewBox="0 0 24 24"
                                            >
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={2}
                                                    d="M6 18L18 6M6 6l12 12"
                                                />
                                            </svg>
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                        {errors.lines && "message" in errors.lines && (
                            <p className="text-sm text-red-500 mt-1">{errors.lines.message}</p>
                        )}
                    </div>

                    <div
                        className={`p-3 rounded-md flex items-center justify-between ${isBalanced
                                ? "bg-[var(--success-muted)] border border-[var(--success)]/30"
                                : "bg-[var(--error-muted)] border border-[var(--error)]/30"
                            }`}
                    >
                        <div className="flex gap-6 text-sm">
                            <div>
                                <span className="text-muted">Debits:</span>{" "}
                                <span className="font-medium">{formatAmount(totalDebits, 2)}</span>
                            </div>
                            <div>
                                <span className="text-muted">Credits:</span>{" "}
                                <span className="font-medium">{formatAmount(totalCredits, 2)}</span>
                            </div>
                        </div>
                        <span
                            className={`text-sm font-medium ${isBalanced ? "text-[var(--success)]" : "text-[var(--error)]"
                                }`}
                        >
                            {isBalanced ? "✓ Balanced" : "⚠ Unbalanced"}
                        </span>
                    </div>

                    {error && <div className="alert-error">{error}</div>}

                    <div className="flex items-center gap-2 py-2">
                        <input
                            type="checkbox"
                            id="postImmediately"
                            checked={postImmediately}
                            onChange={(e) => setPostImmediately(e.target.checked)}
                            className="rounded border-[var(--border)] text-[var(--primary)] focus:ring-[var(--primary)]"
                        />
                        <label htmlFor="postImmediately" className="text-sm cursor-pointer select-none">
                            Post transaction immediately
                        </label>
                    </div>

                    <div className="flex gap-3 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary flex-1">
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={isSubmitting || !isBalanced}
                            className="btn-primary flex-1"
                        >
                            {isSubmitting
                                ? "Processing..."
                                : postImmediately
                                    ? "Create & Post"
                                    : "Create Draft"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
