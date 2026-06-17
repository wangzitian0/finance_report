"use client";

import { formatCurrencyLocale } from "@/lib/money";
import type { BankStatementTransaction } from "@/lib/types";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";

export type Transaction = BankStatementTransaction;

interface TransactionTableProps {
    transactions: Transaction[];
    currency: string;
}

export function TransactionTable({ transactions, currency }: TransactionTableProps) {
    const transactionRows = transactions ?? [];

    return (
        <div className="card flex h-full min-h-0 min-w-0 max-w-full flex-col overflow-hidden">
            <div className="card-header flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h3 className="text-sm font-medium">Transactions</h3>
                <span className="text-xs text-muted">{transactionRows.length} total</span>
            </div>

            <div data-testid="stage1-mobile-transaction-list" className="min-w-0 flex-1 divide-y divide-[var(--border)] overflow-y-auto md:hidden">
                {transactionRows.map((txn) => (
                    <article
                        key={txn.id}
                        data-testid={`stage1-mobile-transaction-card-${txn.id}`}
                        className="min-w-0 space-y-4 p-4"
                    >
                        <div className="flex min-w-0 items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                                <p className="text-xs font-medium uppercase text-muted">Transaction</p>
                                <p className="mt-1 break-words font-medium">{txn.description}</p>
                            </div>
                            <div className="flex-shrink-0">
                                {txn.confidence_tier ? (
                                    <ConfidenceBadge tier={txn.confidence_tier} />
                                ) : (
                                    <span
                                        className={`badge ${
                                            txn.confidence === "high"
                                                ? "badge-success"
                                                : txn.confidence === "medium"
                                                  ? "badge-warning"
                                                  : "badge-error"
                                        }`}
                                    >
                                        {txn.confidence}
                                    </span>
                                )}
                            </div>
                        </div>

                        <div className="grid grid-cols-1 gap-3">
                            <div className="space-y-1.5 text-sm">
                                <span className="block text-xs font-medium uppercase text-muted">Date</span>
                                <p>{txn.txn_date}</p>
                            </div>

                            <div className="space-y-1.5 text-sm">
                                <span className="block text-xs font-medium uppercase text-muted">Direction</span>
                                <p>{txn.direction}</p>
                            </div>

                            <p
                                className={`min-w-0 break-words text-right text-sm font-semibold ${
                                    txn.direction === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"
                                }`}
                            >
                                {txn.direction === "IN" ? "+" : "-"}
                                {formatCurrencyLocale(txn.amount, txn.currency || currency)}
                            </p>
                        </div>
                    </article>
                ))}
            </div>

            <div data-testid="stage1-desktop-transaction-region" className="hidden flex-1 overflow-hidden md:block">
                <table className="table-fixed border-collapse text-sm" style={{ width: "calc(100% - 4px)" }}>
                    <thead className="sticky top-0 bg-[var(--background)]">
                        <tr className="border-b border-[var(--border)]">
                            <th className="text-left px-4 py-2 font-medium w-28">Date</th>
                            <th className="text-left px-4 py-2 font-medium">Description</th>
                            <th className="text-right px-4 py-2 font-medium w-32">Amount</th>
                            <th className="text-center px-4 py-2 font-medium w-24">Confidence</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                        {transactionRows.map((txn) => (
                            <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50 group">
                                <td className="px-4 py-2 whitespace-nowrap">{txn.txn_date}</td>
                                <td className="px-4 py-2">
                                    <div className="max-w-xs truncate" title={txn.description}>
                                        {txn.description}
                                    </div>
                                </td>
                                <td
                                    className={`px-4 py-2 text-right font-medium whitespace-nowrap ${
                                        txn.direction === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"
                                    }`}
                                >
                                    {txn.direction === "IN" ? "+" : "-"}
                                    {formatCurrencyLocale(txn.amount, txn.currency || currency)}
                                </td>
                                <td className="px-4 py-2 text-center">
                                    {txn.confidence_tier ? (
                                        <ConfidenceBadge tier={txn.confidence_tier} />
                                    ) : (
                                        <span
                                            className={`badge ${
                                                txn.confidence === "high"
                                                    ? "badge-success"
                                                    : txn.confidence === "medium"
                                                      ? "badge-warning"
                                                      : "badge-error"
                                            }`}
                                        >
                                            {txn.confidence}
                                        </span>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
