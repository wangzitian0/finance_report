"use client";

import { useState } from "react";
import { formatCurrencyLocale } from "@/lib/currency";
import type { BankStatementTransaction } from "@/lib/types";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";

export type Transaction = BankStatementTransaction;

type EditableField = "txn_date" | "description" | "amount" | "direction";

interface EditingCell {
    txnId: string;
    field: EditableField;
}

interface TransactionTableProps {
    transactions: Transaction[];
    currency: string;
    onEdit: (txnId: string, field: string, value: string) => void;
    pendingEdits: Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>>;
    onSave: () => void;
    onDiscard: () => void;
    actionLoading: boolean;
}

export function TransactionTable({
    transactions,
    currency,
    onEdit,
    pendingEdits,
    onSave,
    onDiscard,
    actionLoading
}: TransactionTableProps) {
    const [editing, setEditing] = useState<EditingCell | null>(null);
    const transactionRows = transactions ?? [];

    const isEditingCell = (txnId: string, field: EditableField) =>
        editing?.txnId === txnId && editing?.field === field;

    const beginEdit = (txnId: string, field: EditableField) => setEditing({ txnId, field });
    const endEdit = () => setEditing(null);

    return (
        <div className="card flex flex-col min-h-0 h-full overflow-hidden">
            <div className="card-header flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                    <h3 className="text-sm font-medium">Transactions</h3>
                    {pendingEdits.size > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                            <button onClick={onSave} disabled={actionLoading} className="btn-primary btn-sm py-1">
                                {actionLoading ? "Saving..." : `Save Edits (${pendingEdits.size})`}
                            </button>
                            <button onClick={onDiscard} disabled={actionLoading} className="btn-secondary btn-sm py-1">
                                Discard
                            </button>
                        </div>
                    )}
                </div>
                <span className="text-xs text-muted">{transactionRows.length} total</span>
            </div>

            <div data-testid="stage1-mobile-transaction-list" className="flex-1 divide-y divide-[var(--border)] overflow-y-auto md:hidden">
                {transactionRows.map((txn) => {
                    const edit = pendingEdits.get(txn.id);
                    const displayDate = edit?.txn_date ?? txn.txn_date;
                    const displayDesc = edit?.description ?? txn.description;
                    const displayAmount = edit?.amount ?? txn.amount.toString();
                    const displayDir = edit?.direction ?? txn.direction;

                    return (
                        <article
                            key={txn.id}
                            data-testid={`stage1-mobile-transaction-card-${txn.id}`}
                            className="space-y-4 p-4"
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <p className="text-xs font-medium uppercase text-muted">Transaction</p>
                                    <p className="mt-1 break-words font-medium">{displayDesc}</p>
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
                                <label className="space-y-1.5 text-sm">
                                    <span className="block text-xs font-medium uppercase text-muted">Date</span>
                                    <input
                                        type="date"
                                        aria-label={`Date for ${txn.id}`}
                                        value={displayDate}
                                        onChange={(e) => onEdit(txn.id, "txn_date", e.target.value)}
                                        className="input text-sm"
                                    />
                                </label>

                                <label className="space-y-1.5 text-sm">
                                    <span className="block text-xs font-medium uppercase text-muted">Description</span>
                                    <input
                                        type="text"
                                        aria-label={`Description for ${txn.id}`}
                                        value={displayDesc}
                                        onChange={(e) => onEdit(txn.id, "description", e.target.value)}
                                        className="input text-sm"
                                    />
                                </label>

                                <div className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)] gap-3">
                                    <label className="space-y-1.5 text-sm">
                                        <span className="block text-xs font-medium uppercase text-muted">Direction</span>
                                        <select
                                            aria-label={`Direction for ${txn.id}`}
                                            value={displayDir}
                                            onChange={(e) => onEdit(txn.id, "direction", e.target.value)}
                                            className="input text-sm"
                                        >
                                            <option value="IN">IN</option>
                                            <option value="OUT">OUT</option>
                                        </select>
                                    </label>

                                    <label className="space-y-1.5 text-sm">
                                        <span className="block text-xs font-medium uppercase text-muted">Amount</span>
                                        <input
                                            type="text"
                                            aria-label={`Amount for ${txn.id}`}
                                            value={displayAmount}
                                            onChange={(e) => onEdit(txn.id, "amount", e.target.value)}
                                            className="input text-right text-sm"
                                        />
                                    </label>
                                </div>

                                <p
                                    className={`text-right text-sm font-semibold ${
                                        displayDir === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"
                                    }`}
                                >
                                    {displayDir === "IN" ? "+" : "-"}
                                    {formatCurrencyLocale(displayAmount, txn.currency || currency)}
                                </p>
                            </div>
                        </article>
                    );
                    })}
            </div>

            <div data-testid="stage1-desktop-transaction-region" className="hidden flex-1 overflow-hidden md:block">
                <table className="w-full table-fixed text-sm">
                    <thead className="sticky top-0 bg-[var(--background)]">
                        <tr className="border-b border-[var(--border)]">
                            <th className="text-left px-4 py-2 font-medium w-28">Date</th>
                            <th className="text-left px-4 py-2 font-medium">Description</th>
                            <th className="text-right px-4 py-2 font-medium w-32">Amount</th>
                            <th className="text-center px-4 py-2 font-medium w-24">Confidence</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                        {transactionRows.map((txn) => {
                            const edit = pendingEdits.get(txn.id);
                            const displayDate = edit?.txn_date ?? txn.txn_date;
                            const displayDesc = edit?.description ?? txn.description;
                            const displayAmount = edit?.amount ?? txn.amount.toString();
                            const displayDir = edit?.direction ?? txn.direction;

                            return (
                                <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50 group">
                                    <td className="px-4 py-2 whitespace-nowrap" onClick={() => beginEdit(txn.id, "txn_date")}>
                                        {isEditingCell(txn.id, "txn_date") ? (
                                            <input
                                                type="date"
                                                value={displayDate}
                                                onChange={(e) => onEdit(txn.id, "txn_date", e.target.value)}
                                                onBlur={endEdit}
                                                onKeyDown={(e) => e.key === "Enter" && endEdit()}
                                                autoFocus
                                                className="input py-0 px-1 text-xs w-full"
                                            />
                                        ) : (
                                            <span className={edit?.txn_date ? "text-[var(--primary)] font-medium" : ""}>{displayDate}</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-2" onClick={() => beginEdit(txn.id, "description")}>
                                        {isEditingCell(txn.id, "description") ? (
                                            <input
                                                type="text"
                                                value={displayDesc}
                                                onChange={(e) => onEdit(txn.id, "description", e.target.value)}
                                                onBlur={endEdit}
                                                onKeyDown={(e) => e.key === "Enter" && endEdit()}
                                                autoFocus
                                                className="input py-0 px-1 text-xs w-full"
                                            />
                                        ) : (
                                            <div
                                                className={`max-w-xs truncate ${edit?.description ? "text-[var(--primary)] font-medium" : ""}`}
                                                title={displayDesc}
                                            >
                                                {displayDesc}
                                            </div>
                                        )}
                                    </td>
                                    <td
                                        className={`px-4 py-2 text-right font-medium whitespace-nowrap ${
                                            displayDir === "IN" ? "text-[var(--success)]" : "text-[var(--error)]"
                                        }`}
                                        onClick={() => {
                                            if (!editing || editing.txnId !== txn.id || (editing.field !== "amount" && editing.field !== "direction")) {
                                                beginEdit(txn.id, "amount");
                                            }
                                        }}
                                    >
                                        {isEditingCell(txn.id, "amount") || isEditingCell(txn.id, "direction") ? (
                                            <div
                                                className="flex items-center gap-1"
                                                onBlur={(e) => {
                                                    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                                                        endEdit();
                                                    }
                                                }}
                                            >
                                                <select
                                                    value={displayDir}
                                                    onChange={(e) => onEdit(txn.id, "direction", e.target.value)}
                                                    onFocus={() => beginEdit(txn.id, "direction")}
                                                    onKeyDown={(e) => e.key === "Enter" && endEdit()}
                                                    className="input py-0 px-1 text-xs w-16"
                                                >
                                                    <option value="IN">IN</option>
                                                    <option value="OUT">OUT</option>
                                                </select>
                                                <input
                                                    type="text"
                                                    value={displayAmount}
                                                    onChange={(e) => onEdit(txn.id, "amount", e.target.value)}
                                                    onFocus={() => beginEdit(txn.id, "amount")}
                                                    onKeyDown={(e) => e.key === "Enter" && endEdit()}
                                                    autoFocus
                                                    className="input py-0 px-1 text-xs w-20 text-right"
                                                />
                                            </div>
                                        ) : (
                                            <span className={edit?.amount || edit?.direction ? "ring-1 ring-[var(--primary)]/30 px-1 rounded" : ""}>
                                                {displayDir === "IN" ? "+" : "-"}
                                                {formatCurrencyLocale(displayAmount, txn.currency || currency)}
                                            </span>
                                        )}
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
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
