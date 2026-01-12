"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { Account } from "@/lib/types";

interface AccountFormModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
    editAccount?: Account | null;
}

const ACCOUNT_TYPES = ["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;
const CURRENCIES = ["SGD", "USD", "EUR", "GBP", "JPY", "CNY", "HKD"];

export default function AccountFormModal({
    isOpen,
    onClose,
    onSuccess,
    editAccount,
}: AccountFormModalProps) {
    const [name, setName] = useState("");
    const [code, setCode] = useState("");
    const [type, setType] = useState<typeof ACCOUNT_TYPES[number]>("ASSET");
    const [currency, setCurrency] = useState("SGD");
    const [description, setDescription] = useState("");
    const [isActive, setIsActive] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const isEditing = !!editAccount;

    useEffect(() => {
        if (editAccount) {
            setName(editAccount.name);
            setCode(editAccount.code || "");
            setType(editAccount.type as typeof ACCOUNT_TYPES[number]);
            setCurrency(editAccount.currency);
            setDescription("");
            setIsActive(true);
        } else {
            setName("");
            setCode("");
            setType("ASSET");
            setCurrency("SGD");
            setDescription("");
            setIsActive(true);
        }
        setError(null);
    }, [editAccount, isOpen]);

    const handleSubmit = useCallback(async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim()) {
            setError("Account name is required");
            return;
        }

        setSaving(true);
        setError(null);

        try {
            if (isEditing && editAccount) {
                await apiFetch(`/api/accounts/${editAccount.id}`, {
                    method: "PUT",
                    body: JSON.stringify({ name: name.trim(), code: code.trim() || null, is_active: isActive }),
                });
            } else {
                await apiFetch("/api/accounts", {
                    method: "POST",
                    body: JSON.stringify({ name: name.trim(), code: code.trim() || null, type, currency, description: description.trim() || null }),
                });
            }
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to save account");
        } finally {
            setSaving(false);
        }
    }, [name, code, type, currency, description, isActive, isEditing, editAccount, onSuccess, onClose]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="fixed inset-0 bg-black/60" onClick={onClose} />
            <div className="relative z-10 w-full max-w-md card animate-slide-up">
                <div className="card-header">
                    <h2 className="text-lg font-semibold">{isEditing ? "Edit Account" : "New Account"}</h2>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1.5">Account Name *</label>
                        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., Cash on Hand" className="input" />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1.5">Account Code</label>
                        <input type="text" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g., 1000" className="input" />
                    </div>

                    {!isEditing && (
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium mb-1.5">Type *</label>
                                <select value={type} onChange={(e) => setType(e.target.value as typeof ACCOUNT_TYPES[number])} className="input">
                                    {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1.5">Currency *</label>
                                <select value={currency} onChange={(e) => setCurrency(e.target.value)} className="input">
                                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                                </select>
                            </div>
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium mb-1.5">Description</label>
                        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional description..." rows={2} className="input resize-none" />
                    </div>

                    {isEditing && (
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="w-4 h-4 rounded border-[var(--border)] bg-[var(--background)] text-[var(--accent)] focus:ring-[var(--accent)]" />
                            <span className="text-sm">Active</span>
                        </label>
                    )}

                    {error && (
                        <div className="alert-error">
                            {error}
                        </div>
                    )}

                    <div className="flex gap-3 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
                        <button type="submit" disabled={saving} className="btn-primary flex-1">
                            {saving ? "Saving..." : isEditing ? "Save Changes" : "Create Account"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
