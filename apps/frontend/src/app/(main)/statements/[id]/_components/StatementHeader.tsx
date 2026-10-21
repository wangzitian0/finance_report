import { useState } from "react";
import Link from "next/link";

import {
    BankStatement,
    BankStatementTransaction,
    BrokerageImportResponse,
} from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/audit/money";
import { formatCategoryLabel } from "@/lib/categories";
import { confidenceLabel } from "@/lib/statusLabels";
import { StatusBadge } from "@/components/ui";
import { LowConfidenceReviewModal } from "@/components/review/LowConfidenceReviewModal";

interface StatementHeaderProps {
    statement: BankStatement;
    statementId: string;
    canImport: boolean;
    canRetry: boolean;
    canDelete?: boolean;
    importLoading: boolean;
    retryLoading: boolean;
    deleteLoading?: boolean;
    onBrokerageImport: () => void;
    onRetry: () => void;
    onDelete?: () => void;
    formatCode: (currency?: string | null) => string;
    formatPeriod: (start?: string | null, end?: string | null) => string;
}

export function StatementHeader({
    statement,
    statementId,
    canImport,
    canRetry,
    canDelete = true,
    importLoading,
    retryLoading,
    deleteLoading = false,
    onBrokerageImport,
    onRetry,
    onDelete,
    formatCode,
    formatPeriod,
}: StatementHeaderProps) {
    const displayTitle =
        statement.original_filename ||
        `${statement.institution} (${statement.period_start ?? ""} – ${statement.period_end ?? ""})`;
    const reviewHref = `/statements/${statement.id || statementId}/review`;

    return (
        <div className="page-header flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex-1 min-w-0 w-full">
                <div className="flex flex-wrap items-center gap-3 mb-2">
                    <h1 className="page-title truncate">{displayTitle}</h1>
                    <StatusBadge
                        status={statement.status}
                        variants={{ approved: "success", rejected: "error", parsed: "warning" }}
                    />
                    {statement.original_filename && (
                        <span
                            data-testid="statement-original-filename-badge"
                            className="inline-flex items-center rounded-md border border-[var(--border)] bg-[var(--background-muted)] px-2.5 py-0.5 text-xs font-medium text-[var(--foreground-muted)]"
                        >
                            Source file: {statement.original_filename}
                        </span>
                    )}
                </div>
                <p className="page-description">
                    {statement.institution} • {formatCode(statement.currency)} • {formatPeriod(statement.period_start, statement.period_end)}
                </p>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2">
                <Link
                    href={reviewHref}
                    className="btn-secondary flex items-center gap-2"
                >
                    Compare PDF & Review
                </Link>
                <Link
                    href={`/statements/${statementId}/review`}
                    className="btn-primary flex items-center gap-2"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                    </svg>
                    Start Review →
                </Link>
                {canImport && (
                    <button
                        type="button"
                        onClick={onBrokerageImport}
                        disabled={importLoading}
                        className="btn-secondary flex items-center gap-2"
                        aria-label="Import brokerage positions to portfolio"
                    >
                        {importLoading ? (
                            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
                            </svg>
                        )}
                        {importLoading ? "Importing..." : "Import to Portfolio"}
                    </button>
                )}
                {canRetry && (
                    <button
                        type="button"
                        onClick={onRetry}
                        disabled={retryLoading}
                        className="btn-secondary flex items-center gap-2"
                    >
                        {retryLoading ? (
                            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                        )}
                        Retry Parse
                    </button>
                )}
                {canDelete && onDelete && (
                    <button
                        type="button"
                        onClick={onDelete}
                        disabled={deleteLoading}
                        className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)] flex items-center gap-2"
                        aria-label="Delete statement"
                    >
                        {deleteLoading ? (
                            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        ) : (
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                        )}
                        Delete
                    </button>
                )}
            </div>
        </div>
    );
}

interface BrokerageImportResultBannerProps {
    importResult: BrokerageImportResponse;
}

export function BrokerageImportResultBanner({ importResult }: BrokerageImportResultBannerProps) {
    return (
        <div className="mb-4 p-4 border border-[var(--success)]/30 bg-[var(--success-muted)] rounded-lg" data-testid="import-result-banner">
            <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-[var(--success)] flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <div className="flex-1 min-w-0">
                    <div className="font-medium text-[var(--success)] mb-2">
                        Brokerage positions imported successfully
                    </div>
                    <div className="text-sm space-y-0.5 mb-3">
                        <div><span className="text-muted">Broker:</span> <span className="font-medium">{importResult.broker}</span></div>
                        <div><span className="text-muted">Positions parsed:</span> <span className="font-medium">{importResult.parsed_positions}</span></div>
                        <div><span className="text-muted">New holdings created:</span> <span className="font-medium">{importResult.created_atomic_positions}</span></div>
                        <div><span className="text-muted">Holdings reconciled:</span> <span className="font-medium">{importResult.reconcile_created + importResult.reconcile_updated}</span></div>
                        {importResult.skipped > 0 && (
                            <div><span className="text-muted">Skipped:</span> <span className="font-medium">{importResult.skipped}</span></div>
                        )}
                    </div>
                    <Link href="/portfolio" className="btn-secondary text-sm" aria-label="View portfolio after import">
                        View Portfolio →
                    </Link>
                </div>
            </div>
        </div>
    );
}

interface StatementSummaryCardsProps {
    statement: BankStatement;
}

export function StatementSummaryCards({ statement }: StatementSummaryCardsProps) {
    return (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Opening Balance</div>
                <div className="text-lg font-semibold">
                    {formatCurrencyLocale(statement.opening_balance ?? 0, statement.currency || "SGD")}
                </div>
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Closing Balance</div>
                <div className="text-lg font-semibold">
                    {formatCurrencyLocale(statement.closing_balance ?? 0, statement.currency || "SGD")}
                </div>
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Confidence Score</div>
                <div className={`text-lg font-semibold ${
                    (statement.confidence_score ?? 0) >= 85 ? "text-[var(--success)]" :
                    (statement.confidence_score ?? 0) >= 60 ? "text-[var(--warning)]" :
                    statement.confidence_score === null || statement.confidence_score === undefined ? "text-muted" :
                    "text-[var(--error)]"
                }`}>
                    {statement.confidence_score ?? "—"}%
                </div>
                {statement.confidence_score !== null && statement.confidence_score !== undefined && (
                    <div className="text-xs text-muted mt-0.5">
                        {confidenceLabel(statement.confidence_score)}
                    </div>
                )}
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Balance Validation</div>
                <div className="flex items-center gap-2">
                    {statement.balance_validated === null || statement.balance_validated === undefined ? (
                        <>
                            <span className="text-muted">…</span>
                            <span className="text-sm font-medium text-muted">Parsing</span>
                        </>
                    ) : statement.balance_validated ? (
                        <>
                            <span className="text-[var(--success)]">✓</span>
                            <span className="text-sm font-medium">Verified</span>
                        </>
                    ) : (
                        <>
                            <span className="text-[var(--warning)]">⚠</span>
                            <span className="text-sm font-medium">Needs Review</span>
                        </>
                    )}
                </div>
                {statement.validation_error && (
                    <div className="text-xs text-[var(--error)] mt-1">{statement.validation_error}</div>
                )}
            </div>
        </div>
    );
}

interface StatementTransactionsTableProps {
    statement: BankStatement;
    onTransactionUpdated?: () => void;
}

export function StatementTransactionsTable({
    statement,
    onTransactionUpdated,
}: StatementTransactionsTableProps) {
    const [selectedTxn, setSelectedTxn] = useState<BankStatementTransaction | null>(null);
    const [isReviewOpen, setIsReviewOpen] = useState(false);

    return (
        <div className="card">
            <div className="card-header flex items-center justify-between">
                <h3 className="text-sm font-medium">Transactions</h3>
                <span className="text-xs text-muted">
                    {statement.transactions.length} total
                </span>
            </div>

            {statement.transactions.length === 0 ? (
                <div className="p-8 text-center text-muted">
                    <p className="text-sm">No transactions found</p>
                </div>
            ) : (
                <div className="max-h-[600px] overflow-auto overflow-x-auto">
                    <table className="w-full min-w-[640px] text-sm">
                        <thead>
                            <tr className="border-b border-[var(--border)] bg-[var(--background-muted)]">
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Date
                                </th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Description
                                </th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Reference
                                </th>
                                <th scope="col" className="text-right px-4 py-3 font-medium">
                                    Amount
                                </th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Currency
                                </th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Balance
                                </th>
                                <th scope="col" className="text-left px-4 py-3 font-medium">
                                    Category
                                </th>
                                <th scope="col" className="text-center px-4 py-3 font-medium">
                                    Confidence
                                </th>
                                <th scope="col" className="text-center px-4 py-3 font-medium">
                                    Status
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border)]">
                            {statement.transactions.map((txn: BankStatementTransaction) => (
                                <tr
                                    key={txn.id}
                                    className="hover:bg-[var(--background-muted)]/50"
                                >
                                    <td className="px-4 py-3 whitespace-nowrap">
                                        {txn.txn_date}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="max-w-xs truncate" title={txn.description}>
                                            {txn.description}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-muted">
                                        {txn.reference || "-"}
                                    </td>
                                    <td
                                        className={`px-4 py-3 text-right font-medium whitespace-nowrap ${
                                            txn.direction === "IN"
                                                ? "text-[var(--success)]"
                                                : "text-[var(--error)]"
                                        }`}
                                    >
                                        {txn.direction === "IN" ? "+" : "-"}
                                        {formatCurrencyLocale(
                                            txn.amount,
                                            (txn.currency ?? statement.currency) || "SGD",
                                        )}
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-[var(--foreground-muted)]">
                                        {txn.currency || "—"}
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-[var(--foreground-muted)]">
                                        {txn.balance_after != null
                                            ? formatCurrencyLocale(
                                                  txn.balance_after,
                                                  (txn.currency ?? statement.currency) || "SGD",
                                              )
                                            : "—"}
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap text-sm text-[var(--foreground)]">
                                        <div className="flex items-center gap-2">
                                            <span>{formatCategoryLabel(txn.category ?? txn.proposed_category) || "—"}</span>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setSelectedTxn(txn);
                                                    setIsReviewOpen(true);
                                                }}
                                                className="rounded px-1.5 py-0.5 text-xs text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)] transition"
                                                title="Edit category"
                                            >
                                                Edit
                                            </button>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <StatusBadge
                                            status={
                                                txn.confidence ??
                                                (txn.confidence_tier === "TRUSTED"
                                                    ? "high"
                                                    : txn.confidence_tier
                                                        ? txn.confidence_tier.toLowerCase()
                                                        : "unavailable")
                                            }
                                            variants={{ high: "success", medium: "warning", low: "muted" }}
                                            fallback="error"
                                        />
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <StatusBadge
                                            status={
                                                txn.status ??
                                                (statement.status === "approved" ? "matched" : "pending")
                                            }
                                            variants={{ pending: "warning", matched: "success", unmatched: "error" }}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {selectedTxn && (
                <LowConfidenceReviewModal
                    isOpen={isReviewOpen}
                    onClose={() => {
                        setIsReviewOpen(false);
                        setSelectedTxn(null);
                    }}
                    transaction={selectedTxn}
                    currency={(selectedTxn.currency ?? statement.currency) || "SGD"}
                    onSuccess={() => {
                        onTransactionUpdated?.();
                    }}
                />
            )}
        </div>
    );
}
