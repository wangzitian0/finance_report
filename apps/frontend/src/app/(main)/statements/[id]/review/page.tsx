"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { formatCurrencyLocale } from "@/lib/currency";
import { formatDateInput } from "@/lib/date";

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
    const [pendingStatements, setPendingStatements] = useState<Array<{ id: string }>>([]);
    const [editingTxnId, setEditingTxnId] = useState<string | null>(null);
    const [pendingEdits, setPendingEdits] = useState<Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>>>(new Map());

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [approveDialogOpen, setApproveDialogOpen] = useState(false);
    const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

    const fetchPendingStatements = useCallback(async () => {
        try {
            const result = await apiFetch<{ items: Array<{ id: string }> }>("/api/statements/pending-review");
            setPendingStatements(result.items);
        } catch (err) {
            console.error("Failed to fetch pending statements:", err);
        }
    }, []);

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
        fetchPendingStatements();
    }, [fetchData, fetchPendingStatements]);

    const handleSaveEdits = async () => {
        setActionLoading(true);
        try {
            const edits = Array.from(pendingEdits.entries()).map(([txn_id, fields]) => ({
                txn_id,
                ...fields,
            }));
            await apiFetch(`/api/statements/${statementId}/review/edit`, {
                method: "POST",
                body: JSON.stringify({ edits }),
            });
            showToast("Edits saved successfully", "success");
            setPendingEdits(new Map());
            fetchData();
        } catch (err) {
            showToast(err instanceof Error ? err.message : "Failed to save edits", "error");
        } finally {
            setActionLoading(false);
        }
    };

    const handleDiscardEdits = () => {
        setPendingEdits(new Map());
        setEditingTxnId(null);
    };

    const handleEditChange = (txnId: string, field: string, value: string) => {
        setPendingEdits((prev) => {
            const newMap = new Map(prev);
            const currentEdit = newMap.get(txnId) || {};
            newMap.set(txnId, { ...currentEdit, [field]: value });
            return newMap;
        });
    };

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
                            <div className="w-12 h-12 bg-[var(--error-muted)] text-[var(--error)] rounded-full flex items-center justify-center mx-auto mb-4">
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
            <div className="mb-4 flex items-center justify-between">
                <Link href="/statements" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Statements
                </Link>

                <div className="flex items-center gap-2">
                    {(() => {
                        const currentIndex = pendingStatements.findIndex((s) => s.id === statementId);
                        const prevId = currentIndex > 0 ? pendingStatements[currentIndex - 1].id : null;
                        const nextId = currentIndex >= 0 && currentIndex < pendingStatements.length - 1 ? pendingStatements[currentIndex + 1].id : null;

                        return (
                            <>
                                <button
                                    onClick={() => prevId && router.push(`/statements/${prevId}/review`)}
                                    disabled={!prevId}
                                    className="btn-ghost btn-sm disabled:opacity-30"
                                    title="Previous pending statement"
                                >
                                    ← Prev
                                </button>
                                <span className="text-xs text-muted">
                                    {currentIndex + 1} / {pendingStatements.length}
                                </span>
                                <button
                                    onClick={() => nextId && router.push(`/statements/${nextId}/review`)}
                                    disabled={!nextId}
                                    className="btn-ghost btn-sm disabled:opacity-30"
                                    title="Next pending statement"
                                >
                                    Next →
                                </button>
                            </>
                        );
                    })()}
                </div>
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
                    <div className="text-lg font-semibold">{formatCurrencyLocale(data.opening_balance ?? 0, data.currency || "SGD")}</div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Closing Balance</div>
                    <div className="text-lg font-semibold">{formatCurrencyLocale(data.closing_balance ?? 0, data.currency || "SGD")}</div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Calculated Closing</div>
                    <div className="text-lg font-semibold">
                        {formatCurrencyLocale(
                            data.balance_validation_result
                                ? parseFloat(data.balance_validation_result.calculated_closing)
                                : 0,
                            data.currency || "SGD"
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
                            <iframe 
                                src={data.pdf_url} 
                                className="w-full h-full rounded border" 
                                title="Statement PDF preview"
                            >
                                <p>PDF preview not available. Use the data table below to review statement content.</p>
                            </iframe>
                        ) : (
                            <div className="w-full h-full flex items-center justify-center text-muted">
                                PDF preview not available
                            </div>
                        )}
                    </div>
                </div>

                <div className="card flex flex-col min-h-0">
                    <div className="card-header flex items-center justify-between">
                        <div className="flex items-center gap-4">
                            <h3 className="text-sm font-medium">Transactions</h3>
                            {pendingEdits.size > 0 && (
                                <div className="flex items-center gap-2">
                                    <button onClick={handleSaveEdits} disabled={actionLoading} className="btn-primary btn-sm py-1">
                                        {actionLoading ? "Saving..." : `Save Edits (${pendingEdits.size})`}
                                    </button>
                                    <button onClick={handleDiscardEdits} disabled={actionLoading} className="btn-secondary btn-sm py-1">
                                        Discard
                                    </button>
                                </div>
                            )}
                        </div>
                        <span className="text-xs text-muted">{data.transactions.length} total</span>
                    </div>
                    <div className="flex-1 overflow-auto">
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-[var(--background)]">
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium w-32">Date</th>
                                    <th className="text-left px-4 py-2 font-medium">Description</th>
                                    <th className="text-right px-4 py-2 font-medium w-40">Amount</th>
                                    <th className="text-center px-4 py-2 font-medium w-24">Confidence</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {data.transactions.map((txn) => {
                                    const edit = pendingEdits.get(txn.id);
                                    const isEditing = editingTxnId === txn.id;
                                    const displayDate = edit?.txn_date ?? txn.txn_date;
                                    const displayDesc = edit?.description ?? txn.description;
                                    const displayAmount = edit?.amount ?? txn.amount.toString();
                                    const displayDir = edit?.direction ?? txn.direction;

                                    return (
                                        <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50 group">
                                            <td className="px-4 py-2 whitespace-nowrap" onClick={() => setEditingTxnId(txn.id)}>
                                                {isEditing ? (
                                                    <input
                                                        type="date"
                                                        value={displayDate}
                                                        onChange={(e) => handleEditChange(txn.id, "txn_date", e.target.value)}
                                                        onBlur={() => setEditingTxnId(null)}
                                                        onKeyDown={(e) => e.key === "Enter" && setEditingTxnId(null)}
                                                        autoFocus
                                                        className="input py-0 px-1 text-xs w-full"
                                                    />
                                                ) : (
                                                    <span className={edit?.txn_date ? "text-[var(--primary)] font-medium" : ""}>{displayDate}</span>
                                                )}
                                            </td>
                                            <td className="px-4 py-2" onClick={() => setEditingTxnId(txn.id)}>
                                                {isEditing ? (
                                                    <input
                                                        type="text"
                                                        value={displayDesc}
                                                        onChange={(e) => handleEditChange(txn.id, "description", e.target.value)}
                                                        onBlur={() => setEditingTxnId(null)}
                                                        onKeyDown={(e) => e.key === "Enter" && setEditingTxnId(null)}
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
                                                onClick={() => setEditingTxnId(txn.id)}
                                            >
                                                {isEditing ? (
                                                    <div className="flex items-center gap-1">
                                                        <select
                                                            value={displayDir}
                                                            onChange={(e) => handleEditChange(txn.id, "direction", e.target.value)}
                                                            className="input py-0 px-1 text-xs w-16"
                                                        >
                                                            <option value="IN">IN</option>
                                                            <option value="OUT">OUT</option>
                                                        </select>
                                                        <input
                                                            type="text"
                                                            value={displayAmount}
                                                            onChange={(e) => handleEditChange(txn.id, "amount", e.target.value)}
                                                            onBlur={() => setEditingTxnId(null)}
                                                            onKeyDown={(e) => e.key === "Enter" && setEditingTxnId(null)}
                                                            autoFocus
                                                            className="input py-0 px-1 text-xs w-20 text-right"
                                                        />
                                                    </div>
                                                ) : (
                                                    <span className={edit?.amount || edit?.direction ? "ring-1 ring-[var(--primary)]/30 px-1 rounded" : ""}>
                                                        {displayDir === "IN" ? "+" : "-"}
                                                        {formatCurrencyLocale(displayAmount, txn.currency || data.currency || "SGD")}
                                                    </span>
                                                )}
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
                                    );
                                })}
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
