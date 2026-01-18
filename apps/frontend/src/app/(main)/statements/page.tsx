"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import StatementUploader from "@/components/statements/StatementUploader";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementListResponse } from "@/lib/types";

export default function StatementsPage() {
    const { showToast } = useToast();
    const [statements, setStatements] = useState<BankStatement[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [polling, setPolling] = useState(false);

    const fetchStatements = useCallback(async () => {
        try {
            const data = await apiFetch<BankStatementListResponse>("/api/statements");
            setStatements(data.items);
            setError(null);

            const hasParsing = data.items.some((s) => s.status === "parsing");
            setPolling(hasParsing);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load statements");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchStatements();
    }, [fetchStatements]);

    useEffect(() => {
        if (!polling) return;

        const interval = setInterval(fetchStatements, 3000);
        return () => {
            clearInterval(interval);
        };
    }, [polling, fetchStatements]);

    const handleDeleteStatement = async (e: React.MouseEvent, id: string) => {
        e.preventDefault();
        e.stopPropagation();
        if (!window.confirm("Are you sure you want to delete this statement?")) return;
        
        try {
            await apiFetch(`/api/statements/${id}`, { method: "DELETE" });
            showToast("Statement deleted successfully", "success");
            fetchStatements();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to delete statement");
        }
    };

    const formatCurrency = (currency?: string | null) => currency || "—";

    const formatAmount = (amount?: number | null) => {
        if (amount === null || amount === undefined) return "—";
        return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    const formatPeriod = (start?: string | null, end?: string | null) => {
        if (!start || !end) return "Parsing...";
        return `${start} → ${end}`;
    };

    return (
        <div className="p-6">
            {/* Header */}
            <div className="page-header">
                <h1 className="page-title">Bank Statements</h1>
                <p className="page-description">
                    Upload bank statements for AI-powered parsing and reconciliation.
                </p>
            </div>

            {/* Upload Section */}
            <div className="mb-6">
                <StatementUploader
                    onUploadComplete={fetchStatements}
                    onError={setError}
                />
            </div>

            {/* Error Display */}
            {error && (
                <div className="mb-4 alert-error">
                    {error}
                </div>
            )}

            {/* Polling Indicator */}
            {polling && (
                <div className="mb-4 flex items-center gap-2 text-sm text-[var(--accent)]">
                    <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    <span>Updating...</span>
                </div>
            )}

            {/* Statements List */}
            <div className="card">
                <div className="card-header flex items-center justify-between">
                    <h3 className="text-sm font-medium">Uploaded Statements</h3>
                    <span className="text-xs text-muted">{statements.length} total</span>
                </div>

                {loading ? (
                    <div className="p-8 text-center text-muted">
                        <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                        <p className="text-sm">Loading statements...</p>
                    </div>
                ) : error ? (
                    <div className="p-8 text-center" role="alert" aria-live="polite">
                        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-soft)] text-[var(--error)] mb-4">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        </div>
                        <p className="text-[var(--foreground)] font-medium mb-2">Failed to load statements</p>
                        <p className="text-sm text-muted mb-6">{error}</p>
                        <button
                            onClick={fetchStatements}
                            className="btn-secondary"
                            aria-label="Retry loading statements"
                        >
                            Retry
                        </button>
                    </div>
                ) : statements.length === 0 ? (
                    <div className="p-8 text-center text-muted">
                        <p className="text-sm">No statements uploaded yet</p>
                    </div>
                ) : (
                    <div className="divide-y divide-[var(--border)]">
                        {statements.map((statement) => (
                            <Link
                                key={statement.id}
                                href={`/statements/${statement.id}`}
                                className="block px-6 py-4 hover:bg-[var(--background-muted)]/50 transition-colors cursor-pointer"
                            >
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="font-medium truncate">{statement.original_filename}</span>
                                            <span className={`badge ${statement.status === "approved" ? "badge-success" :
                                                statement.status === "rejected" ? "badge-error" :
                                                    statement.status === "parsed" ? "badge-warning" :
                                                        "badge-muted"
                                                }`}>
                                                {statement.status}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-3 text-xs text-muted">
                                            <span>{statement.institution}</span>
                                            <span>•</span>
                                            <span>{formatPeriod(statement.period_start, statement.period_end)}</span>
                                            <span>•</span>
                                            <span>{formatCurrency(statement.currency)}</span>
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0 flex flex-col items-end gap-2">
                                        <button
                                            onClick={(e) => handleDeleteStatement(e, statement.id)}
                                            className="text-muted hover:text-[var(--error)] p-1 transition-colors"
                                            title="Delete Statement"
                                        >
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                            </svg>
                                        </button>
                                        <div>
                                            <div className="text-lg font-semibold text-[var(--accent)]">
                                                {statement.confidence_score ?? "—"}%
                                            </div>
                                            <div className="text-xs text-muted">{statement.transactions.length} txns</div>
                                        </div>
                                    </div>
                                </div>

                                <div className="mt-3 flex items-center gap-6 text-xs">
                                    <div>
                                        <span className="text-muted">Opening:</span>{" "}
                                        <span>
                                            {formatCurrency(statement.currency)} {formatAmount(statement.opening_balance)}
                                        </span>
                                    </div>
                                    <div>
                                        <span className="text-muted">Closing:</span>{" "}
                                        <span>
                                            {formatCurrency(statement.currency)} {formatAmount(statement.closing_balance)}
                                        </span>
                                    </div>
                                    {statement.balance_validated === null || statement.balance_validated === undefined ? (
                                        <span className="badge badge-muted">Parsing</span>
                                    ) : statement.balance_validated ? (
                                        <span className="badge badge-success">✓ Verified</span>
                                    ) : (
                                        <span className="badge badge-warning">Needs Review</span>
                                    )}
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
