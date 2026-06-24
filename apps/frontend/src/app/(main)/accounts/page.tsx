"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Scale, Trash2 } from "lucide-react";

import AccountFormModal from "@/components/accounts/AccountFormModal";
import { FilterTabs } from "@/components/ui/FilterTabs";
import OpeningBalanceModal from "@/components/accounts/OpeningBalanceModal";
import AccountDetailsSidebar from "@/components/accounts/AccountDetailsSidebar";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { Alert, Badge, Button, EmptyState, IconButton, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/money";
import { Account, AccountListResponse } from "@/lib/types";

const ACCOUNT_TYPES = ["All", "ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"] as const;

export default function AccountsPage() {
    const { showToast } = useToast();
    const queryClient = useQueryClient();
    const [activeFilter, setActiveFilter] = useState<string>("All");
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isOpeningBalanceOpen, setIsOpeningBalanceOpen] = useState(false);
    const [editingAccount, setEditingAccount] = useState<Account | null>(null);
    const [selectedAccount, setSelectedAccount] = useState<Account | null>(null);

    const { data, isLoading, error, refetch } = useQuery({
        queryKey: ["accounts"],
        queryFn: () => apiFetch<AccountListResponse>("/api/accounts?include_balance=true"),
    });

    // #949: nudge the user if they have activity but no recorded opening balances,
    // so they don't silently ship an incomplete balance sheet.
    const { data: readiness } = useQuery({
        queryKey: ["opening-balance-readiness"],
        queryFn: () =>
            apiFetch<{ needs_opening_balance: boolean; earliest_activity_date: string | null }>(
                "/api/accounts/opening-balance-readiness",
            ),
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

    const deleteDialog = useConfirmDialog(async (accountId) => {
        try {
            await deleteMutation.mutateAsync(accountId);
        } catch {
            // onError handler already shows the toast; close the dialog regardless.
        }
    });

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
        <div className="p-4 sm:p-6">
            <PageHeader
                title="Accounts"
                description="Manage your chart of accounts"
                actions={(
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            variant="secondary"
                            onClick={() => setIsOpeningBalanceOpen(true)}
                            className="flex items-center gap-2"
                        >
                            <Scale className="h-4 w-4" aria-hidden="true" />
                            Set opening balances
                        </Button>
                        <Button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }} className="flex items-center gap-2">
                            <Plus className="h-4 w-4" aria-hidden="true" />
                            Add Account
                        </Button>
                    </div>
                )}
            />

            {/* #949 readiness nudge: warn before shipping a silently-incomplete balance sheet. */}
            {readiness?.needs_opening_balance && (
                <Alert variant="warning" className="mb-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <span>
                            Your balance sheet may be incomplete — you have activity
                            {readiness.earliest_activity_date ? ` since ${readiness.earliest_activity_date}` : ""} but
                            no opening balances recorded. Set your starting balances so reports tie out from day one.
                        </span>
                        <Button
                            variant="secondary"
                            onClick={() => setIsOpeningBalanceOpen(true)}
                            className="shrink-0"
                        >
                            Set opening balances
                        </Button>
                    </div>
                </Alert>
            )}

            {/* Tabs */}
            <FilterTabs
                options={ACCOUNT_TYPES}
                value={activeFilter}
                onChange={setActiveFilter}
                className="mb-6 flex w-full flex-wrap gap-1 rounded-lg bg-[var(--background-muted)] p-1 sm:w-fit"
            />

            {/* Error */}
            {error && (
                <Alert variant="error" className="mb-4">
                    {error instanceof Error ? error.message : "Failed to load accounts"}
                </Alert>
            )}

            {/* Content */}
            {isLoading ? (
                <LoadingState label="Loading accounts" />
            ) : error ? (
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load accounts</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <Button
                        variant="secondary"
                        onClick={() => refetch()}
                        aria-label="Retry loading accounts"
                    >
                        Retry
                    </Button>
                </div>
            ) : filteredAccounts.length === 0 ? (
                <EmptyState
                    title="No accounts yet"
                    action={(
                        <Button onClick={() => { setEditingAccount(null); setIsModalOpen(true); }}>
                            Create First Account
                        </Button>
                    )}
                />
            ) : (
                <div className="space-y-4">
                    {Object.entries(groupedAccounts).map(([type, typeAccounts]) => (
                        <div key={type} className="card">
                            <div className="card-header flex items-center justify-between">
                                <Badge variant="primary">{type}</Badge>
                                <span className="text-xs text-muted">{typeAccounts.length} accounts</span>
                            </div>
                            <div className="divide-y divide-[var(--border)]">
                                {typeAccounts.map((account) => (
                                    <div
                                        key={account.id}
                                        data-testid={`account-row-${account.id}`}
                                        className="flex cursor-pointer flex-col gap-3 px-4 py-4 transition-colors hover:bg-[var(--background-muted)]/50 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                                        onClick={() => setSelectedAccount(account)}
                                    >
                                        <div data-account-field="identity" className="min-w-0 flex-1">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <span className="break-words font-medium">{account.name}</span>
                                                {account.code && <span className="text-xs text-muted font-mono">{account.code}</span>}
                                                {!account.is_active && <Badge variant="muted">Inactive</Badge>}
                                            </div>
                                            {account.description && <p className="break-words text-xs text-muted sm:truncate">{account.description}</p>}
                                        </div>
                                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-2">
                                            <div data-account-field="balance" className="text-left sm:mr-2 sm:text-right">
                                                <div className="font-semibold">{formatCurrencyLocale(account.balance ?? 0, account.currency)}</div>
                                            </div>
                                            <div data-account-field="actions" className="flex items-center gap-2">
                                                <IconButton
                                                    icon={Pencil}
                                                    label="Edit Account"
                                                    onClick={(e) => { e.stopPropagation(); setEditingAccount(account); setIsModalOpen(true); }}
                                                    className="hover:text-[var(--accent)]"
                                                />
                                                <IconButton
                                                    icon={Trash2}
                                                    label="Delete Account"
                                                    onClick={(e) => { e.stopPropagation(); deleteDialog.open(account.id); }}
                                                    className="text-muted hover:text-[var(--error)]"
                                                    disabled={deleteMutation.isPending}
                                                />
                                            </div>
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

            <OpeningBalanceModal
                isOpen={isOpeningBalanceOpen}
                onClose={() => setIsOpeningBalanceOpen(false)}
                onSuccess={() => {
                    showToast("Opening balances recorded", "success");
                    queryClient.invalidateQueries({ queryKey: ["accounts"] });
                    queryClient.invalidateQueries({ queryKey: ["opening-balance-readiness"] });
                }}
                accounts={accounts}
            />

            <ConfirmDialog
                isOpen={deleteDialog.isOpen}
                onCancel={deleteDialog.cancel}
                onConfirm={() => deleteDialog.confirm()}
                title="Delete Account"
                message="Are you sure you want to delete this account? This will only work if there are no transactions."
                confirmLabel="Delete Account"
                confirmVariant="danger"
                loading={deleteMutation.isPending}
            />

            <AccountDetailsSidebar
                account={selectedAccount}
                isOpen={!!selectedAccount}
                onClose={() => setSelectedAccount(null)}
            />
        </div>
    );
}
