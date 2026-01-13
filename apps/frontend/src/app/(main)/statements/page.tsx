"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import StatementUploader from "@/components/statements/StatementUploader";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementListResponse } from "@/lib/types";

export default function StatementsPage() {
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
                                            <span>{statement.period_start} → {statement.period_end}</span>
                                            <span>•</span>
                                            <span>{statement.currency}</span>
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-lg font-semibold text-[var(--accent)]">
                                            {statement.confidence_score}%
                                        </div>
                                        <div className="text-xs text-muted">{statement.transactions.length} txns</div>
                                    </div>
                                </div>

                                <div className="mt-3 flex items-center gap-6 text-xs">
                                    <div>
                                        <span className="text-muted">Opening:</span>{" "}
                                        <span>{statement.currency} {statement.opening_balance.toLocaleString()}</span>
                                    </div>
                                    <div>
                                        <span className="text-muted">Closing:</span>{" "}
                                        <span>{statement.currency} {statement.closing_balance.toLocaleString()}</span>
                                    </div>
                                    {statement.balance_validated ? (
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
