import { BankStatement, BankStatementTransaction } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/money";
import { StatusBadge } from "@/components/ui";

interface StatementTransactionsTableProps {
    statement: BankStatement;
}

export function StatementTransactionsTable({ statement }: StatementTransactionsTableProps) {
    return (
        <div className="card">
            <div className="card-header flex items-center justify-between">
                <h3 className="text-sm font-medium">Transactions</h3>
                <span className="text-xs text-muted">{statement.transactions.length} total</span>
            </div>

            {statement.transactions.length === 0 ? (
                <div className="p-8 text-center text-muted">
                    <p className="text-sm">No transactions found</p>
                </div>
            ) : (
                <div className="max-h-[600px] overflow-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-[var(--border)] bg-[var(--background-muted)]">
                                <th scope="col" className="text-left px-4 py-3 font-medium">Date</th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">Description</th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">Reference</th>
                                <th scope="col" className="text-right px-4 py-3 font-medium">Amount</th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">Currency</th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">Balance</th>
                                <th scope="col" className="text-center px-4 py-3 font-medium">Confidence</th>
                                <th scope="col" className="text-center px-4 py-3 font-medium">Status</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border)]">
                            {statement.transactions.map((txn: BankStatementTransaction) => (
                                <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50">
                                    <td className="px-4 py-3 whitespace-nowrap">{txn.txn_date}</td>
                                    <td className="px-4 py-3">
                                        <div className="max-w-xs truncate" title={txn.description}>
                                            {txn.description}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-muted">
                                        {txn.reference || "-"}
                                    </td>
                                    <td className={`px-4 py-3 text-right font-medium whitespace-nowrap ${
                                        txn.direction === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"
                                    }`}>
                                        {txn.direction === "IN" ? "+" : "-"}{formatCurrencyLocale(txn.amount, (txn.currency ?? statement.currency) || "SGD")}
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-[var(--foreground-muted)]">{txn.currency || "—"}</td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-[var(--foreground-muted)]">{txn.balance_after != null ? formatCurrencyLocale(txn.balance_after, (txn.currency ?? statement.currency) || "SGD") : "—"}</td>
                                    <td className="px-4 py-3 text-center">
                                        <StatusBadge
                                            status={txn.confidence}
                                            variants={{ high: "success", medium: "warning" }}
                                            fallback="error"
                                        />
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <StatusBadge
                                            status={txn.status}
                                            variants={{ matched: "success", unmatched: "error" }}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
