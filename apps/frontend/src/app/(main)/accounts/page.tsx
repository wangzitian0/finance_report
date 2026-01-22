"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import AccountFormModal from "@/components/accounts/AccountFormModal";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { Account, AccountListResponse } from "@/lib/types";

const ACCOUNT_TYPES = ["All", "ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;

export default function AccountsPage() {
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [activeFilter, setActiveFilter] = useState<string>("All");
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingAccount, setEditingAccount] = useState<Account | null>(null);

    const { data, isLoading, error, refetch } = useQuery({
        queryKey: ["accounts"],
        queryFn: () => apiFetch<AccountListResponse>("/api/accounts?include_balance=true"),
    });

    const deleteMutation = useMutation({
        mutationFn: (accountId: string) => apiFetch(`/api/accounts/${accountId}`, { method: "DELETE" }),
        onSuccess: () => {
            showToast("Account deleted successfully", "success");
            queryClient.invalidateQueries({ queryKey: ["accounts"] });
        },
        onError: (err: Error) => {
            showToast(`Failed to delete account: ${err.message}`, "error");
        },
    });

    const handleDeleteAccount = async (accountId: string) => {
        if (!window.confirm("Are you sure you want to delete this account? This will only work if there are no transactions.")) return;
        deleteMutation.mutate(accountId);
    };

    const handleModalSuccess = () => {
        queryClient.invalidateQueries({ queryKey: ["accounts"] });
    };

    const accounts = data?.items ?? [];
    const filteredAccounts = activeFilter === "All"
        ? accounts
        : accounts.filter((a) => a.type === activeFilter);

    const groupedAccounts = filteredAccounts.reduce((groups, account) => {
        const type = account.type;
        if (!groups[type]) groups[type] = [];
        groups[type].push(account);
        return groups;
    }, {} as Record<string, Account[]>);

    return (
        <div className="p-6">
            {/* Header */}
            <div className="page-header flex items-center justify-between">
                <div>
                    <h1 className="page-title">Accounts</h1>
                    <p className="page-description">Manage your chart of accounts</p>
                </div>
                <button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }} className="btn-primary flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Add Account
                </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 mb-6 bg-[var(--background-muted)] p-1 rounded-lg w-fit">
                {ACCOUNT_TYPES.map((type) => (
                    <button
                        key={type}
                        onClick={() => setActiveFilter(type)}
                        className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${activeFilter === type
                            ? "bg-[var(--background-card)] text-[var(--foreground)]"
                            : "text-muted hover:text-[var(--foreground)]"
                            }`}
                    >
                        {type}
                    </button>
                ))}
            </div>

            {/* Error */}
            {error && (
                <div className="mb-4 alert-error">
                    {error instanceof Error ? error.message : "Failed to load accounts"}
                </div>
            )}

            {/* Content */}
            {isLoading ? (
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading accounts...</p>
                </div>
            ) : error ? (
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-soft)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load accounts</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <button
                        onClick={() => refetch()}
                        className="btn-secondary"
                        aria-label="Retry loading accounts"
                    >
                        Retry
                    </button>
                </div>
            ) : filteredAccounts.length === 0 ? (
                <div className="card p-8 text-center">
                    <p className="text-muted mb-4">No accounts yet</p>
                    <button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }} className="btn-primary">
                        Create First Account
                    </button>
                </div>
            ) : (
                <div className="space-y-4">
                    {Object.entries(groupedAccounts).map(([type, typeAccounts]) => (
                        <div key={type} className="card">
                            <div className="card-header flex items-center justify-between">
                                <span className="badge badge-primary">{type}</span>
                                <span className="text-xs text-muted">{typeAccounts.length} accounts</span>
                            </div>
                            <div className="divide-y divide-[var(--border)]">
                                {typeAccounts.map((account) => (
                                    <div key={account.id} className="px-6 py-3 flex items-center justify-between hover:bg-[var(--background-muted)]/50 transition-colors">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium">{account.name}</span>
                                                {account.code && <span className="text-xs text-muted font-mono">{account.code}</span>}
                                                {!account.is_active && <span className="badge badge-muted">Inactive</span>}
                                            </div>
                                            {account.description && <p className="text-xs text-muted truncate">{account.description}</p>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <div className="text-right mr-2">
                                                <div className="font-semibold">{account.currency} {(account.balance ?? 0).toLocaleString()}</div>
                                            </div>
                                            <button
                                                onClick={() => { setEditingAccount(account); setIsModalOpen(true); }}
                                                className="btn-ghost p-2 hover:text-[var(--accent)]"
                                                title="Edit Account"
                                            >
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                                </svg>
                                            </button>
                                            <button
                                                onClick={() => handleDeleteAccount(account.id)}
                                                className="btn-ghost p-2 text-muted hover:text-[var(--error)]"
                                                title="Delete Account"
                                                disabled={deleteMutation.isPending}
                                            >
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                </svg>
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <AccountFormModal
                isOpen={isModalOpen}
                onClose={() => { setIsModalOpen(false); setEditingAccount(null); }}
                onSuccess={handleModalSuccess}
                editAccount={editingAccount}
            />
        </div>
    );
}
