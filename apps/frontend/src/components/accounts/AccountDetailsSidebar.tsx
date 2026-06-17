"use client";

import { useQuery } from "@tanstack/react-query";
import Sheet from "@/components/ui/Sheet";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/money";
import { Account, JournalEntryListResponse } from "@/lib/types";

interface AccountDetailsSidebarProps {
    account: Account | null;
    isOpen: boolean;
    onClose: () => void;
}

export default function AccountDetailsSidebar({
    account,
    isOpen,
    onClose,
}: AccountDetailsSidebarProps) {
    const { data, isLoading } = useQuery({
        queryKey: ["account-transactions", account?.id],
        queryFn: () =>
            account
                ? apiFetch<JournalEntryListResponse>(`/api/journal-entries?limit=50`)
                : Promise.resolve({ items: [], total: 0 }),
        enabled: !!account && isOpen,
    });

    if (!account) return null;

    const entries = (data?.items ?? []).filter(e => e.lines.some(l => l.account_id === account.id)).slice(0, 10);

    return (
        <Sheet isOpen={isOpen} onClose={onClose} title="Account Details">
            <div className="space-y-8">
                <div className="space-y-4">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <h3 className="text-xl font-bold text-[var(--foreground)]">{account.name}</h3>
                            <span className="badge badge-primary">{account.type}</span>
                        </div>
                        {account.code && (
                            <p className="text-sm font-mono text-muted">{account.code}</p>
                        )}
                    </div>

                    <div className="grid grid-cols-2 gap-4 pt-2">
                        <div>
                            <p className="text-xs text-muted mb-1">Currency</p>
                            <p className="font-medium">{account.currency}</p>
                        </div>
                        <div>
                            <p className="text-xs text-muted mb-1">Status</p>
                            <span className={`badge ${account.is_active ? "badge-success" : "badge-muted"}`}>
                                {account.is_active ? "Active" : "Inactive"}
                            </span>
                        </div>
                        <div className="col-span-2">
                            <p className="text-xs text-muted mb-1">Current Balance</p>
                            <p className="text-2xl font-bold text-[var(--foreground)]">
                                {formatCurrencyLocale(account.balance ?? 0, account.currency)}
                            </p>
                        </div>
                    </div>

                    {account.description && (
                        <div>
                            <p className="text-xs text-muted mb-1">Description</p>
                            <p className="text-sm">{account.description}</p>
                        </div>
                    )}
                </div>

                <div className="space-y-4">
                    <h4 className="font-semibold border-b border-[var(--border)] pb-2">Recent Transactions</h4>
                    
                    {isLoading ? (
                        <div className="flex justify-center py-8">
                            <div className="w-6 h-6 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : entries.length === 0 ? (
                        <div className="text-center py-8 text-sm text-muted bg-[var(--background-muted)]/30 rounded-lg border border-dashed border-[var(--border)]">
                            No recent transactions found
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {entries.map((entry) => {
                                const accountLines = entry.lines.filter(l => l.account_id === account.id);
                                return accountLines.map((line, idx) => (
                                    <div key={`${entry.id}-${idx}`} className="p-3 rounded-lg border border-[var(--border)] hover:bg-[var(--background-muted)]/50 transition-colors">
                                        <div className="flex justify-between items-start gap-4 mb-1">
                                            <p className="text-sm font-medium truncate flex-1">{entry.memo}</p>
                                            <p className={`text-sm font-bold ${line.direction === "DEBIT" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                                                {line.direction === "DEBIT" ? "+" : "-"}
                                                {formatCurrencyLocale(line.amount, line.currency)}
                                            </p>
                                        </div>
                                        <div className="flex justify-between items-center text-[10px] text-muted">
                                            <span>{new Date(entry.entry_date).toLocaleDateString()}</span>
                                            <span className="uppercase">{line.direction}</span>
                                        </div>
                                    </div>
                                ));
                            })}
                        </div>
                    )}
                </div>
            </div>
        </Sheet>
    );
}
