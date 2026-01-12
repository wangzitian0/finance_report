"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementTransaction } from "@/lib/types";

export default function StatementDetailPage() {
    const params = useParams();
    const router = useRouter();
    const statementId = params.id as string;

    const [statement, setStatement] = useState<BankStatement | null>(null);
    const [loading, setLoading] = useState(true);
    const [processing, setProcessing] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchStatement = useCallback(async () => {
        try {
            const data = await apiFetch<BankStatement>(`/api/statements/${statementId}`);
            setStatement(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load statement");
        } finally {
            setLoading(false);
        }
    }, [statementId]);

    useEffect(() => {
        fetchStatement();
    }, [fetchStatement]);

    const handleApprove = async () => {
        if (!statement) return;
        setProcessing(true);
        try {
            await apiFetch(`/api/statements/${statementId}/approve`, {
                method: "POST",
                body: JSON.stringify({}),
            });
            router.push("/statements");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to approve");
        } finally {
            setProcessing(false);
        }
    };

    const handleReject = async () => {
        if (!statement) return;
        setProcessing(true);
        try {
            await apiFetch(`/api/statements/${statementId}/reject`, {
                method: "POST",
                body: JSON.stringify({}),
            });
            router.push("/statements");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to reject");
        } finally {
            setProcessing(false);
        }
    };

    if (loading) {
        return (
            <div className="p-6">
                <div className="text-center py-12">
                    <div className="inline-block w-6 h-6 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    <p className="mt-2 text-muted">Loading statement...</p>
                </div>
            </div>
        );
    }

    if (error || !statement) {
        return (
            <div className="p-6">
                <div className="alert-error">{error || "Statement not found"}</div>
                <button onClick={() => router.push("/statements")} className="btn-secondary mt-4">
                    Back to Statements
                </button>
            </div>
        );
    }

    const statusColors: Record<string, string> = {
        approved: "badge-success",
        rejected: "badge-error",
        parsed: "badge-warning",
        parsing: "badge-info",
        uploaded: "badge-muted",
    };

    const directionColors: Record<string, string> = {
        IN: "text-[var(--success)]",
        OUT: "text-[var(--error)]",
    };

    return (
        <div className="p-6">
            {/* Header */}
            <div className="mb-6">
                <button
                    onClick={() => router.push("/statements")}
                    className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1 mb-4"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Statements
                </button>

                <div className="flex items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <h1 className="text-xl font-semibold">{statement.original_filename}</h1>
                            <span className={`badge ${statusColors[statement.status] || "badge-muted"}`}>
                                {statement.status}
                            </span>
                        </div>
                        <div className="text-sm text-muted">
                            <span>{statement.institution}</span>
                            <span className="mx-2">•</span>
                            <span>{statement.period_start} → {statement.period_end}</span>
                            <span className="mx-2">•</span>
                            <span>{statement.currency}</span>
                        </div>
                    </div>
                    <div className="text-right">
                        <div className="text-2xl font-bold text-[var(--accent)]">
                            {statement.confidence_score}%
                        </div>
                        <div className="text-xs text-muted">Confidence</div>
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-4 gap-4 mb-6">
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Opening Balance</div>
                    <div className="text-lg font-semibold">
                        {statement.currency} {Number(statement.opening_balance).toLocaleString()}
                    </div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Closing Balance</div>
                    <div className="text-lg font-semibold">
                        {statement.currency} {Number(statement.closing_balance).toLocaleString()}
                    </div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Transactions</div>
                    <div className="text-lg font-semibold">{statement.transactions.length}</div>
                </div>
                <div className="card p-4">
                    <div className="text-xs text-muted mb-1">Validation</div>
                    <div className="flex items-center gap-2">
                        {statement.balance_validated ? (
                            <>
                                <span className="text-[var(--success)]">✓ Verified</span>
                            </>
                        ) : (
                            <span className="text-[var(--warning)]">Needs Review</span>
                        )}
                    </div>
                </div>
            </div>

            {/* Validation Error */}
            {statement.validation_error && (
                <div className="alert-warning mb-6">
                    <strong>Validation Note:</strong> {statement.validation_error}
                </div>
            )}

            {/* Actions */}
            {statement.status === "parsed" && (
                <div className="flex gap-3 mb-6">
                    <button
                        onClick={handleApprove}
                        disabled={processing}
                        className="btn-primary flex items-center gap-2"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        Approve & Create Entries
                    </button>
                    <button
                        onClick={handleReject}
                        disabled={processing}
                        className="btn-secondary flex items-center gap-2 text-[var(--error)]"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                        Reject
                    </button>
                    <button
                        onClick={async () => {
                            if (!statement) return;
                            setProcessing(true);
                            try {
                                await apiFetch(`/api/statements/${statement.id}/retry`, {
                                    method: "POST",
                                });
                                await fetchStatement();
                            } catch (err) {
                                setError(err instanceof Error ? err.message : "Retry failed");
                            } finally {
                                setProcessing(false);
                            }
                        }}
                        disabled={processing}
                        className="btn-secondary flex items-center gap-2"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Retry with Stronger Model
                    </button>
                </div>
            )}

            {/* Transactions Table */}
            <div className="card">
                <div className="card-header">
                    <h3 className="text-sm font-medium">Transactions ({statement.transactions.length})</h3>
                </div>
                {statement.transactions.length === 0 ? (
                    <div className="p-8 text-center text-muted text-sm">
                        No transactions extracted
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-[var(--border)] text-xs text-muted">
                                    <th className="text-left py-3 px-4 font-medium">Date</th>
                                    <th className="text-left py-3 px-4 font-medium">Description</th>
                                    <th className="text-right py-3 px-4 font-medium">Amount</th>
                                    <th className="text-center py-3 px-4 font-medium">Confidence</th>
                                    <th className="text-center py-3 px-4 font-medium">Status</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {statement.transactions.map((txn) => (
                                    <tr key={txn.id} className="hover:bg-[var(--background-muted)]/50">
                                        <td className="py-3 px-4 text-sm">{txn.txn_date}</td>
                                        <td className="py-3 px-4 text-sm max-w-xs truncate" title={txn.description}>
                                            {txn.description}
                                        </td>
                                        <td className={`py-3 px-4 text-sm text-right font-medium ${directionColors[txn.direction] || ""}`}>
                                            {txn.direction === "OUT" ? "-" : "+"}
                                            {statement.currency} {Number(txn.amount).toLocaleString()}
                                        </td>
                                        <td className="py-3 px-4 text-sm text-center">
                                            <span className={`badge ${
                                                txn.confidence === "high" ? "badge-success" :
                                                txn.confidence === "medium" ? "badge-warning" :
                                                "badge-error"
                                            }`}>
                                                {txn.confidence}
                                            </span>
                                        </td>
                                        <td className="py-3 px-4 text-sm text-center">
                                            <span className={`badge ${
                                                txn.status === "matched" ? "badge-success" :
                                                txn.status === "pending" ? "badge-warning" :
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
        </div>
    );
}
