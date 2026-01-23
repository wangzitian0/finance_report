"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementTransaction } from "@/lib/types";

export default function StatementDetailPage() {
    const { showToast } = useToast();
    const params = useParams();
    const statementId = params.id as string;

    const [statement, setStatement] = useState<BankStatement | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [retryLoading, setRetryLoading] = useState(false);
    const [polling, setPolling] = useState(false);
    const [consecutiveErrors, setConsecutiveErrors] = useState(0);
    const [pollingStoppedReason, setPollingStoppedReason] = useState<string | null>(null);
    
    // Dialog states
    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

    const fetchStatement = useCallback(async () => {
        try {
            const data = await apiFetch<BankStatement>(`/api/statements/${statementId}`);
            setStatement(data);
            setError(null);
            setConsecutiveErrors(0);
            
            // Enable polling if statement is still parsing
            setPolling(data.status === "parsing");
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : "Failed to load statement";
            
            setConsecutiveErrors(prev => {
                const newCount = prev + 1;
                
                if (polling && newCount >= 3) {
                    setPolling(false);
                    const reason = `Auto-refresh stopped after 3 consecutive errors. Last error: ${errorMessage}`;
                    setPollingStoppedReason(reason);
                    showToast("Auto-refresh stopped due to repeated errors", "error");
                }
                
                return newCount;
            });
            
            setError(errorMessage);
        } finally {
            setLoading(false);
        }
    }, [statementId, polling, showToast]);

    const resumePolling = useCallback(() => {
        setPollingStoppedReason(null);
        setConsecutiveErrors(0);
        setPolling(true);
        fetchStatement();
    }, [fetchStatement]);

    useEffect(() => {
        fetchStatement();
    }, [fetchStatement]);

    // Auto-refresh while parsing
    useEffect(() => {
        if (!polling) return;

        const interval = setInterval(fetchStatement, 3000);
        return () => {
            clearInterval(interval);
        };
    }, [polling, fetchStatement]);

    const handleApproveConfirm = async () => {
        setActionLoading(true);
        try {
            await apiFetch(`/api/statements/${statementId}/approve`, {
                method: "POST",
                body: JSON.stringify({ notes: null }),
            });
            showToast("Statement approved successfully", "success");
            setApproveDialogOpen(false);
            await fetchStatement();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to approve statement";
            showToast(message, "error");
            setError(message);
        } finally {
            setActionLoading(false);
        }
    };

    const handleRejectConfirm = async (reason?: string) => {
        setActionLoading(true);
        try {
            await apiFetch(`/api/statements/${statementId}/reject`, {
                method: "POST",
                body: JSON.stringify({ notes: reason || null }),
            });
            showToast("Statement rejected", "success");
            setRejectDialogOpen(false);
            await fetchStatement();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to reject statement";
            showToast(message, "error");
            setError(message);
        } finally {
            setActionLoading(false);
        }
    };

    const handleRetry = async () => {
        setRetryLoading(true);
        try {
            await apiFetch(`/api/statements/${statementId}/retry`, {
                method: "POST",
            });
            showToast("Re-parsing started", "success");
            await fetchStatement();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to retry parsing";
            showToast(message, "error");
            setError(message);
        } finally {
            setRetryLoading(false);
        }
    };

    const formatAmount = (amount: number, direction: string) => {
        const sign = direction === "IN" ? "+" : "-";
        return `${sign}${Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    };

    const formatCurrency = (amount?: number | null) => {
        if (amount === null || amount === undefined) return "—";
        return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    const formatCode = (currency?: string | null) => currency || "—";

    const formatPeriod = (start?: string | null, end?: string | null) => {
        if (!start || !end) return "Parsing...";
        return `${start} to ${end}`;
    };

    if (loading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading statement...</p>
                </div>
            </div>
        );
    }

    if (!statement) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center">
                    <p className="text-muted mb-4">Statement not found</p>
                    <Link href="/statements" className="btn-primary">
                        Back to Statements
                    </Link>
                </div>
            </div>
        );
    }

    const canApproveReject = statement.status === "parsed";
    const canRetry = statement.status === "parsed" || statement.status === "rejected";

    return (
        <div className="p-6">
            {/* Breadcrumb */}
            <div className="mb-4">
                <Link href="/statements" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Statements
                </Link>
            </div>

            {/* Polling Stopped Alert */}
            {pollingStoppedReason && (
                <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg">
                    <div className="flex items-start gap-3">
                        <svg className="w-5 h-5 text-[var(--error)] flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        <div className="flex-1 min-w-0">
                            <div className="font-medium text-[var(--error)] mb-1">Auto-refresh Stopped</div>
                            <div className="text-sm text-[var(--foreground-muted)] mb-3">{pollingStoppedReason}</div>
                            <button 
                                onClick={resumePolling}
                                className="btn-secondary text-sm"
                            >
                                Resume Auto-Refresh
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Header */}
            <div className="page-header flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                        <h1 className="page-title truncate">{statement.original_filename}</h1>
                        <span className={`badge ${
                            statement.status === "approved" ? "badge-success" :
                            statement.status === "rejected" ? "badge-error" :
                            statement.status === "parsed" ? "badge-warning" :
                            "badge-muted"
                        }`}>
                            {statement.status}
                        </span>
                    </div>
                    <p className="page-description">
                        {statement.institution} • {formatCode(statement.currency)} • {formatPeriod(statement.period_start, statement.period_end)}
                    </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 flex-shrink-0">
                    {canRetry && (
                        <button
                            onClick={handleRetry}
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
                    {canApproveReject && (
                        <>
                            <button
                                onClick={() => setRejectDialogOpen(true)}
                                disabled={actionLoading}
                                className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                            >
                                Reject
                            </button>
                            <button
                                onClick={() => setApproveDialogOpen(true)}
                                disabled={actionLoading}
                                className="btn-primary"
                            >
                                {actionLoading ? "Processing..." : "Approve"}
                            </button>
                        </>
                    )}
                </div>
            </div>

            {/* Error */}
            {error && (
                <div className="mb-4 alert-error">
                    {error}
                </div>
            )}

            {/* Parsing Progress Indicator */}
            {polling && (
                <div className="mb-4 card p-4">
                    <div className="flex items-center gap-3">
                        <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                        <div>
                            <div className="text-sm font-medium text-[var(--accent)]">Parsing in progress...</div>
                            <div className="text-xs text-muted mt-0.5">
                                AI is extracting transaction data. This may take up to 3 minutes.
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Opening Balance</div>
                    <div className="text-lg font-semibold">
                        {formatCode(statement.currency)} {formatCurrency(statement.opening_balance)}
                    </div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Closing Balance</div>
                    <div className="text-lg font-semibold">
                        {formatCode(statement.currency)} {formatCurrency(statement.closing_balance)}
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

            {/* Transactions Table */}
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
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[var(--border)] bg-[var(--background-muted)]">
                                    <th className="text-left px-4 py-3 font-medium">Date</th>
                                    <th className="text-left px-4 py-3 font-medium">Description</th>
                                    <th className="text-left px-4 py-3 font-medium">Reference</th>
                                    <th className="text-right px-4 py-3 font-medium">Amount</th>
                                    <th className="text-center px-4 py-3 font-medium">Confidence</th>
                                    <th className="text-center px-4 py-3 font-medium">Status</th>
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
                                            {formatAmount(txn.amount, txn.direction)}
                                        </td>
                                        <td className="px-4 py-3 text-center">
                                            <span className={`badge ${
                                                txn.confidence === "high" ? "badge-success" :
                                                txn.confidence === "medium" ? "badge-warning" :
                                                "badge-error"
                                            }`}>
                                                {txn.confidence}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-center">
                                            <span className={`badge ${
                                                txn.status === "matched" ? "badge-success" :
                                                txn.status === "unmatched" ? "badge-error" :
                                                "badge-muted"
                                            }`}>
                                                {txn.status}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Confirm Dialogs */}
            <ConfirmDialog
                isOpen={approveDialogOpen}
                onCancel={() => !actionLoading && setApproveDialogOpen(false)}
                onConfirm={handleApproveConfirm}
                title="Approve Statement"
                message="This will create journal entries for all transactions in this statement. Are you sure?"
                confirmLabel="Approve"
                loading={actionLoading}
            />

            <ConfirmDialog
                isOpen={rejectDialogOpen}
                onCancel={() => !actionLoading && setRejectDialogOpen(false)}
                onConfirm={handleRejectConfirm}
                title="Reject Statement"
                message="This will mark the statement as rejected. You can re-parse it later."
                confirmLabel="Reject"
                confirmVariant="danger"
                showInput
                inputLabel="Rejection Reason (optional)"
                inputPlaceholder="Enter reason for rejection..."
                loading={actionLoading}
            />
        </div>
    );
}
