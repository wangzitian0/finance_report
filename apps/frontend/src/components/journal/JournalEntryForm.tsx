"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

interface Account {
    id: string;
    name: string;
    code?: string;
    type: string;
    currency: string;
}

interface JournalLineInput {
    account_id: string;
    direction: "DEBIT" | "CREDIT";
    amount: string;
    currency: string;
}

interface JournalEntryFormProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export default function JournalEntryForm({ isOpen, onClose, onSuccess }: JournalEntryFormProps) {
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [entryDate, setEntryDate] = useState(new Date().toISOString().split("T")[0]);
    const [memo, setMemo] = useState("");
    const [lines, setLines] = useState<JournalLineInput[]>([
        { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" },
        { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" },
    ]);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            apiFetch<{ items: Account[] }>("/api/accounts").then((data) => setAccounts(data.items)).catch(() => setAccounts([]));
        }
    }, [isOpen]);

    const totalDebits = lines.filter((l) => l.direction === "DEBIT" && l.amount).reduce((sum, l) => sum + parseFloat(l.amount || "0"), 0);
    const totalCredits = lines.filter((l) => l.direction === "CREDIT" && l.amount).reduce((sum, l) => sum + parseFloat(l.amount || "0"), 0);
    const isBalanced = Math.abs(totalDebits - totalCredits) < 0.01;

    const addLine = () => setLines([...lines, { account_id: "", direction: "DEBIT", amount: "", currency: "SGD" }]);
    const removeLine = (index: number) => lines.length > 2 && setLines(lines.filter((_, i) => i !== index));
    const updateLine = (index: number, field: keyof JournalLineInput, value: string) => {
        const updated = [...lines];
        updated[index] = { ...updated[index], [field]: value };
        setLines(updated);
    };

    const handleSubmit = useCallback(async (e: React.FormEvent) => {
        e.preventDefault();
        if (!memo.trim()) { setError("Memo is required"); return; }
        const validLines = lines.filter((l) => l.account_id && l.amount);
        if (validLines.length < 2) { setError("At least 2 lines with account and amount are required"); return; }
        if (!isBalanced) { setError("Entry must be balanced (Debits = Credits)"); return; }

        setSaving(true);
        setError(null);

        try {
            await apiFetch("/api/journal-entries", {
                method: "POST",
                body: JSON.stringify({
                    entry_date: entryDate, memo: memo.trim(), source_type: "manual",
                    lines: validLines.map((l) => ({ account_id: l.account_id, direction: l.direction, amount: parseFloat(l.amount), currency: l.currency })),
                }),
            });
            setMemo("");
            setEntryDate(new Date().toISOString().split("T")[0]);
            setLines([{ account_id: "", direction: "DEBIT", amount: "", currency: "SGD" }, { account_id: "", direction: "CREDIT", amount: "", currency: "SGD" }]);
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to create entry");
        } finally {
            setSaving(false);
        }
    }, [entryDate, memo, lines, isBalanced, onSuccess, onClose]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto p-4">
            <div className="fixed inset-0 bg-black/60" onClick={onClose} />
            <div className="relative z-10 w-full max-w-2xl card animate-slide-up my-8">
                <div className="card-header">
                    <h2 className="text-lg font-semibold">New Journal Entry</h2>
                    <p className="text-sm text-muted">Create a balanced double-entry transaction</p>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Date *</label>
                            <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} className="input" />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Memo *</label>
                            <input type="text" value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="Description" className="input" />
                        </div>
                    </div>

                    <div>
                        <div className="flex items-center justify-between mb-3">
                            <label className="text-sm font-medium">Journal Lines</label>
                            <button type="button" onClick={addLine} className="text-sm text-[var(--accent)] hover:underline">+ Add Line</button>
                        </div>
                        <div className="space-y-2">
                            {lines.map((line, index) => (
                                <div key={index} className="flex gap-2 items-center">
                                    <select value={line.account_id} onChange={(e) => updateLine(index, "account_id", e.target.value)} className="input flex-1 text-sm">
                                        <option value="">Select Account</option>
                                        {accounts.map((acc) => <option key={acc.id} value={acc.id}>{acc.code ? `${acc.code} - ` : ""}{acc.name}</option>)}
                                    </select>
                                    <select value={line.direction} onChange={(e) => updateLine(index, "direction", e.target.value)} className={`input w-24 text-sm ${line.direction === "DEBIT" ? "text-[var(--info)]" : "text-[var(--success)]"}`}>
                                        <option value="DEBIT">Debit</option>
                                        <option value="CREDIT">Credit</option>
                                    </select>
                                    <input type="number" step="0.01" min="0" value={line.amount} onChange={(e) => updateLine(index, "amount", e.target.value)} placeholder="0.00" className="input w-28 text-sm text-right" />
                                    {lines.length > 2 && (
                                        <button type="button" onClick={() => removeLine(index)} className="btn-ghost p-2 text-muted hover:text-[var(--error)]">
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                                        </button>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className={`p-3 rounded-md flex items-center justify-between ${isBalanced ? "bg-[var(--success-muted)] border border-[var(--success)]/30" : "bg-[var(--error-muted)] border border-[var(--error)]/30"}`}>
                        <div className="flex gap-6 text-sm">
                            <div><span className="text-muted">Debits:</span> <span className="font-medium">{totalDebits.toFixed(2)}</span></div>
                            <div><span className="text-muted">Credits:</span> <span className="font-medium">{totalCredits.toFixed(2)}</span></div>
                        </div>
                        <span className={`text-sm font-medium ${isBalanced ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                            {isBalanced ? "✓ Balanced" : "⚠ Unbalanced"}
                        </span>
                    </div>

                    {error && <div className="alert-error">{error}</div>}

                    <div className="flex gap-3 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
                        <button type="submit" disabled={saving || !isBalanced} className="btn-primary flex-1">{saving ? "Creating..." : "Create Entry"}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}
