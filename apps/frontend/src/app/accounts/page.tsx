"use client";

import { useCallback, useEffect, useState } from "react";

import AccountFormModal from "@/components/accounts/AccountFormModal";
import { apiFetch } from "@/lib/api";
import { Account, AccountListResponse } from "@/lib/types";

const ACCOUNT_TYPES = ["All", "ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;

export default function AccountsPage() {
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeFilter, setActiveFilter] = useState<string>("All");
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingAccount, setEditingAccount] = useState<Account | null>(null);

    const fetchAccounts = useCallback(async () => {
        setLoading(true);
        try {
            const data = await apiFetch<AccountListResponse>("/api/accounts?include_balance=true");
            setAccounts(data.items);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load accounts");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAccounts();
    }, [fetchAccounts]);

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
                    {error}
                </div>
            )}

            {/* Content */}
            {loading ? (
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading accounts...</p>
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
                                        <div className="flex items-center gap-4">
                                            <div className="text-right">
                                                <div className="font-semibold">{account.currency} {(account.balance ?? 0).toLocaleString()}</div>
                                            </div>
                                            <button
                                                onClick={() => { setEditingAccount(account); setIsModalOpen(true); }}
                                                className="btn-ghost p-2"
                                            >
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
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
                onSuccess={fetchAccounts}
                editAccount={editingAccount}
            />
        </div>
    );
}
