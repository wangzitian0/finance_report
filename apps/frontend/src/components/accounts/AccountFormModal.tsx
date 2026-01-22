"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { apiFetch } from "@/lib/api";
import { Account } from "@/lib/types";

interface AccountFormModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
    editAccount?: Account | null;
}

const ACCOUNT_TYPES = ["ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;
const CURRENCIES = ["SGD", "USD", "EUR", "GBP", "JPY", "CNY", "HKD"] as const;

const createAccountSchema = z.object({
    name: z.string().min(1, "Account name is required").trim(),
    code: z.string().trim().optional(),
    type: z.enum(ACCOUNT_TYPES),
    currency: z.enum(CURRENCIES),
    description: z.string().trim().optional(),
});

const editAccountSchema = z.object({
    name: z.string().min(1, "Account name is required").trim(),
    code: z.string().trim().optional(),
    is_active: z.boolean(),
});

type CreateAccountForm = z.infer<typeof createAccountSchema>;
type EditAccountForm = z.infer<typeof editAccountSchema>;

export default function AccountFormModal({
    isOpen,
    onClose,
    onSuccess,
    editAccount,
}: AccountFormModalProps) {
    const [error, setError] = useState<string | null>(null);
    const isEditing = !!editAccount;

    const createForm = useForm<CreateAccountForm>({
        resolver: zodResolver(createAccountSchema),
        defaultValues: { name: "", code: "", type: "ASSET", currency: "SGD", description: "" },
    });

    const editForm = useForm<EditAccountForm>({
        resolver: zodResolver(editAccountSchema),
        defaultValues: { name: "", code: "", is_active: true },
    });

    useEffect(() => {
        if (editAccount) {
            editForm.reset({
                name: editAccount.name,
                code: editAccount.code || "",
                is_active: true,
            });
        } else {
            createForm.reset();
        }
        setError(null);
    }, [editAccount, isOpen, createForm, editForm]);

    const handleCreateSubmit = async (data: CreateAccountForm) => {
        setError(null);
        try {
            await apiFetch("/api/accounts", {
                method: "POST",
                body: JSON.stringify({
                    name: data.name,
                    code: data.code || null,
                    type: data.type,
                    currency: data.currency,
                    description: data.description || null,
                }),
            });
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to create account");
        }
    };

    const handleEditSubmit = async (data: EditAccountForm) => {
        if (!editAccount) return;
        setError(null);
        try {
            await apiFetch(`/api/accounts/${editAccount.id}`, {
                method: "PUT",
                body: JSON.stringify({
                    name: data.name,
                    code: data.code || null,
                    is_active: data.is_active,
                }),
            });
            onSuccess();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to update account");
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="fixed inset-0 bg-black/60" onClick={onClose} />
            <div className="relative z-10 w-full max-w-md card animate-slide-up">
                <div className="card-header">
                    <h2 className="text-lg font-semibold">{isEditing ? "Edit Account" : "New Account"}</h2>
                </div>

                {isEditing ? (
                    <form onSubmit={editForm.handleSubmit(handleEditSubmit)} className="p-6 space-y-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Account Name *</label>
                            <input
                                type="text"
                                {...editForm.register("name")}
                                placeholder="e.g., Cash on Hand"
                                className="input"
                            />
                            {editForm.formState.errors.name && (
                                <p className="text-sm text-red-500 mt-1">{editForm.formState.errors.name.message}</p>
                            )}
                        </div>

                        <div>
                            <label className="block text-sm font-medium mb-1.5">Account Code</label>
                            <input
                                type="text"
                                {...editForm.register("code")}
                                placeholder="e.g., 1000"
                                className="input"
                            />
                            {editForm.formState.errors.code && (
                                <p className="text-sm text-red-500 mt-1">{editForm.formState.errors.code.message}</p>
                            )}
                        </div>

                        <label className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                {...editForm.register("is_active")}
                                className="w-4 h-4 rounded border-[var(--border)] bg-[var(--background)] text-[var(--accent)] focus:ring-[var(--accent)]"
                            />
                            <span className="text-sm">Active</span>
                        </label>

                        {error && <div className="alert-error">{error}</div>}

                        <div className="flex gap-3 pt-2">
                            <button type="button" onClick={onClose} className="btn-secondary flex-1">
                                Cancel
                            </button>
                            <button type="submit" disabled={editForm.formState.isSubmitting} className="btn-primary flex-1">
                                {editForm.formState.isSubmitting ? "Saving..." : "Save Changes"}
                            </button>
                        </div>
                    </form>
                ) : (
                    <form onSubmit={createForm.handleSubmit(handleCreateSubmit)} className="p-6 space-y-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Account Name *</label>
                            <input
                                type="text"
                                {...createForm.register("name")}
                                placeholder="e.g., Cash on Hand"
                                className="input"
                            />
                            {createForm.formState.errors.name && (
                                <p className="text-sm text-red-500 mt-1">{createForm.formState.errors.name.message}</p>
                            )}
                        </div>

                        <div>
                            <label className="block text-sm font-medium mb-1.5">Account Code</label>
                            <input
                                type="text"
                                {...createForm.register("code")}
                                placeholder="e.g., 1000"
                                className="input"
                            />
                            {createForm.formState.errors.code && (
                                <p className="text-sm text-red-500 mt-1">{createForm.formState.errors.code.message}</p>
                            )}
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium mb-1.5">Type *</label>
                                <select {...createForm.register("type")} className="input">
                                    {ACCOUNT_TYPES.map((t) => (
                                        <option key={t} value={t}>
                                            {t}
                                        </option>
                                    ))}
                                </select>
                                {createForm.formState.errors.type && (
                                    <p className="text-sm text-red-500 mt-1">{createForm.formState.errors.type.message}</p>
                                )}
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1.5">Currency *</label>
                                <select {...createForm.register("currency")} className="input">
                                    {CURRENCIES.map((c) => (
                                        <option key={c} value={c}>
                                            {c}
                                        </option>
                                    ))}
                                </select>
                                {createForm.formState.errors.currency && (
                                    <p className="text-sm text-red-500 mt-1">{createForm.formState.errors.currency.message}</p>
                                )}
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium mb-1.5">Description</label>
                            <textarea
                                {...createForm.register("description")}
                                placeholder="Optional description..."
                                rows={2}
                                className="input resize-none"
                            />
                            {createForm.formState.errors.description && (
                                <p className="text-sm text-red-500 mt-1">{createForm.formState.errors.description.message}</p>
                            )}
                        </div>

                        {error && <div className="alert-error">{error}</div>}

                        <div className="flex gap-3 pt-2">
                            <button type="button" onClick={onClose} className="btn-secondary flex-1">
                                Cancel
                            </button>
                            <button type="submit" disabled={createForm.formState.isSubmitting} className="btn-primary flex-1">
                                {createForm.formState.isSubmitting ? "Saving..." : "Create Account"}
                            </button>
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}
