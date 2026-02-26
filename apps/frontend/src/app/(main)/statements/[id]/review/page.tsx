"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";

interface BalanceValidationResult {
    opening_balance: string;
    closing_balance: string;
    calculated_closing: string;
    opening_delta: string;
    closing_delta: string;
    opening_match: boolean;
    closing_match: boolean;
    validated_at: string;
}

interface Transaction {
    id: string;
    txn_date: string;
    description: string;
    amount: string | number;
    direction: string;
    reference: string | null;
    currency: string | null;
    balance_after: string | number | null;
    status: string;
    confidence: string;
}

interface StatementReview {
    id: string;
    original_filename: string;
    institution: string;
    currency: string | null;
    period_start: string | null;
    period_end: string | null;
    opening_balance: string | number | null;
    closing_balance: string | number | null;
    status: string;
    stage1_status: string | null;
    balance_validation_result: BalanceValidationResult | null;
    pdf_url: string | null;
    transactions: Transaction[];
}

export default function StatementReviewPage() {
    const { showToast } = useToast();
    const params = useParams();
    const router = useRouter();
    const statementId = params.id as string;

    const [data, setData] = useState<StatementReview | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

    const fetchData = useCallback(async () => {
        try {
            const result = await apiFetch<StatementReview>(`/api/statements/${statementId}/review`);
            setData(result);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load review data");
        } finally {
            setLoading(false);
        }
    }, [statementId]);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    const handleApprove = async () => {
        setActionLoading(true);
        try {
            await apiFetch(`/api/statements/${statementId}/review/approve`, { method: "POST" });
            showToast("Statement approved successfully", "success");
            setApproveDialogOpen(false);
            router.push("/statements");
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to approve", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const handleReject = async (reason?: string) => {
        setActionLoading(true);
        try {
            await apiFetch(`/api/statements/${statementId}/review/reject`, {
                method: "POST",
                body: JSON.stringify({ notes: reason || null }),
            });
            showToast("Statement rejected", "success");
            setRejectDialogOpen(false);
            router.push("/statements");
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to reject", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const formatAmount = (amount: string | number, direction: string) => {
        const num = typeof amount === "string" ? parseFloat(amount) : amount;
        const sign = direction === "IN" ? "+" : "-";
        return `${sign}${Math.abs(num).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    };

    const formatCurrency = (amount?: string | number | null, currency?: string | null) => {
        if (amount === null || amount === undefined) return "—";
        const num = typeof amount === "string" ? parseFloat(amount) : amount;
        return `${currency || ""} ${num.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    };

    if (loading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading review data...</p>
                </div>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="p-6">
                <div className="card p-12 text-center max-w-md mx-auto">
                    {error ? (
                        <>
                            <div className="w-12 h-12 bg-red-100 text-red-600 rounded-full flex items-center justify-center mx-auto mb-4">
                                <span className="text-xl font-bold">!</span>
                            </div>
                            <h2 className="text-lg font-medium mb-2">Failed to load statement</h2>
                            <p className="text-muted mb-6">{error}</p>
                            <div className="flex gap-3 justify-center">
                                <button type="button" onClick={fetchData} className="btn-primary">
                                    Retry
                                </button>
                                <Link href="/statements" className="btn-secondary">
                                    Back to Statements
                                </Link>
                            </div>
                        </>
                    ) : (
                        <>
                            <p className="text-muted mb-6">Statement not found</p>
                            <Link href="/statements" className="btn-primary">
                                Back to Statements
                            </Link>
                        </>
                    )}
                </div>
            </div>
        );
    }

    const balanceValid = data.balance_validation_result?.closing_match ?? false;

    return (
        <div className="p-6 h-[calc(100vh-2rem)] flex flex-col">
            <div className="mb-4">
                <Link href="/statements" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Statements
                </Link>
            </div>

            <div className="page-header flex items-start justify-between gap-4 mb-4">
                <div>
                    <h1 className="page-title">{data.original_filename}</h1>
                    <p className="page-description">
                        {data.institution} • {data.currency || "—"} • {data.period_start || "?"} to {data.period_end || "?"}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={() => setRejectDialogOpen(true)}
                        disabled={actionLoading}
                        className="btn-secondary text-[var(--error)] border-[var(--error)]/30 hover:bg-[var(--error-muted)]"
                    >
                        Reject
                    </button>
                    <button
                        type="button"
                        onClick={() => setApproveDialogOpen(true)}
                        disabled={actionLoading || !balanceValid}
                        className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                        title={!balanceValid ? "Balance validation failed - cannot approve" : ""}
                    >
                        {actionLoading ? "Processing..." : "Approve"}
                    </button>
                </div>
            </div>

            {error && <div className="mb-4 alert-error">{error}</div>}

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Opening Balance</div>
                    <div className="text-lg font-semibold">{formatCurrency(data.opening_balance, data.currency)}</div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Closing Balance</div>
                    <div className="text-lg font-semibold">{formatCurrency(data.closing_balance, data.currency)}</div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Calculated Closing</div>
                    <div className="text-lg font-semibold">
                        {formatCurrency(
                            data.balance_validation_result
                                ? parseFloat(data.balance_validation_result.calculated_closing)
                                : null,
                            data.currency
                        )}
                    </div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Balance Validation</div>
                    <div className="flex items-center gap-2">
                        {balanceValid ? (
                            <>
                                <span className="text-[var(--success)]">✓</span>
                                <span className="text-sm font-medium text-[var(--success)]">Valid</span>
                            </>
                        ) : (
                            <>
                                <span className="text-[var(--error)]">✗</span>
                                <span className="text-sm font-medium text-[var(--error)]">
                                    Mismatch (Δ: {data.balance_validation_result?.closing_delta || "?"})
                                </span>
                            </>
                        )}
                    </div>
                </div>
            </div>

            <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-0">
                <div className="card flex flex-col min-h-0">
                    <div className="card-header">
                        <h3 className="text-sm font-medium">PDF Preview</h3>
                    </div>
                    <div className="flex-1 p-4 min-h-0">
                        {data.pdf_url ? (
                            <iframe src={data.pdf_url} className="w-full h-full rounded border" title="PDF Preview" />
                        ) : (
                            <div className="w-full h-full flex items-center justify-center text-muted">
                                PDF preview not available
                            </div>
                        )}
                    </div>
                </div>

                <div className="card flex flex-col min-h-0">
                    <div className="card-header flex items-center justify-between">
                        <h3 className="text-sm font-medium">Transactions</h3>
                        <span className="text-xs text-muted">{data.transactions.length} total</span>
                    </div>
                    <div className="flex-1 overflow-auto">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-[var(--background)]">
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium">Date</th>
                                    <th className="text-left px-4 py-2 font-medium">Description</th>
                                    <th className="text-right px-4 py-2 font-medium">Amount</th>
                                    <th className="text-center px-4 py-2 font-medium">Confidence</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {data.transactions.map((txn) => (
                                    <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50">
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
                                            {formatAmount(txn.amount, txn.direction)}
                                        </td>
                                        <td className="px-4 py-2 text-center">
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
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <ConfirmDialog
                isOpen={approveDialogOpen}
                onCancel={() => !actionLoading && setApproveDialogOpen(false)}
                onConfirm={handleApprove}
                title="Approve Statement"
                message="This will approve the statement with balance validation. Proceed?"
                confirmLabel="Approve"
                loading={actionLoading}
            />

            <ConfirmDialog
                isOpen={rejectDialogOpen}
                onCancel={() => !actionLoading && setRejectDialogOpen(false)}
                onConfirm={handleReject}
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
