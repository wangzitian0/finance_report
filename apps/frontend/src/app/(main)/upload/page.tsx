"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";

import StatementUploader from "@/components/statements/StatementUploader";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";
import { Alert, Badge, Button, EmptyState, IconButton, LoadingState, PageHeader } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementListResponse } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/currency";

export default function UploadPage() {
    const { showToast } = useToast();
    const [statements, setStatements] = useState<BankStatement[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [polling, setPolling] = useState(false);
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
    const [deletingStatementId, setDeletingStatementId] = useState<string | null>(null);

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

    const handleDeleteStatement = (e: React.MouseEvent, id: string) => {
        e.preventDefault();
        e.stopPropagation();
        setDeletingStatementId(id);
        setDeleteDialogOpen(true);
    };

    const handleDeleteConfirm = async () => {
        if (!deletingStatementId) return;
        try {
            await apiFetch(`/api/statements/${deletingStatementId}`, { method: "DELETE" });
            showToast("Statement deleted successfully", "success");
            setDeleteDialogOpen(false);
            setDeletingStatementId(null);
            fetchStatements();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to delete statement");
        }
    };

    const formatCurrency = (currency?: string | null) => currency || "—";

    const formatPeriod = (start?: string | null, end?: string | null) => {
        if (!start || !end) return "Parsing...";
        return `${start} → ${end}`;
    };

    return (
        <div className="p-6">
            <PageHeader
                title="Upload"
                description="Upload bank statements for AI parsing, and review your upload history."
                className="sm:block"
            />

            {/* Upload Section */}
            <div className="mb-6">
                <StatementUploader
                    onUploadComplete={fetchStatements}
                    onError={setError}
                />
            </div>

            {/* Error Display */}
            {error && (
                <Alert variant="error" className="mb-4">
                    {error}
                </Alert>
            )}

            {/* Parsing Progress */}
            {polling && (
                <div className="mb-4 p-4 border border-[var(--accent)]/30 bg-[var(--accent-muted)] rounded-lg">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                        <div className="flex-1">
                            <div className="text-sm font-medium text-[var(--accent)]">AI Parsing in Progress</div>
                            <div className="text-xs text-muted">Extracting transactions from your statement...</div>
                        </div>
                    </div>
                    <div className="h-1.5 bg-[var(--background-muted)] rounded-full overflow-hidden">
                        <div
                            className="h-full bg-[var(--accent)] rounded-full animate-pulse"
                            style={{ width: '60%' }}
                            role="status"
                            aria-label="Loading statements"
                            aria-live="polite"
                        />
                    </div>
                </div>
            )}

            {/* Statements List */}
            <div className="card">
                <div className="card-header flex items-center justify-between">
                    <h3 className="text-sm font-medium">Uploaded Statements</h3>
                    <span className="text-xs text-muted">{statements.length} total</span>
                </div>

                {loading ? (
                    <LoadingState label="Loading statements" framed={false} />
                ) : error ? (
                    <EmptyState
                        framed={false}
                        role="alert"
                        aria-live="polite"
                        title="Failed to load statements"
                        description={error}
                        action={(
                            <Button
                                variant="secondary"
                                onClick={fetchStatements}
                                aria-label="Retry loading statements"
                            >
                                Retry
                            </Button>
                        )}
                    />
                ) : statements.length === 0 ? (
                    <EmptyState framed={false} title="No statements uploaded yet" />
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
                                            <Badge variant={statement.status === "approved" ? "success" :
                                                statement.status === "rejected" ? "error" :
                                                    statement.status === "parsed" ? "warning" :
                                                        "muted"
                                            }>
                                                {statement.status === "parsing" && (
                                                    <span className="inline-block w-3 h-3 mr-1 border-2 border-current border-t-transparent rounded-full animate-spin" />
                                                )}
                                                {statement.status}
                                            </Badge>
                                        </div>
                                        {statement.status === "rejected" && statement.validation_error && (
                                            <div className="text-xs text-[var(--error)] mt-1 line-clamp-2">
                                                {statement.validation_error}
                                            </div>
                                        )}
                                        <div className="flex items-center gap-3 text-xs text-muted">
                                            <span>{statement.institution}</span>
                                            <span>•</span>
                                            <span>{formatPeriod(statement.period_start, statement.period_end)}</span>
                                            <span>•</span>
                                            <span>{formatCurrency(statement.currency)}</span>
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0 flex flex-col items-end gap-2">
                                        <IconButton
                                            icon={Trash2}
                                            label="Delete Statement"
                                            onClick={(e) => handleDeleteStatement(e, statement.id)}
                                            className="text-muted hover:text-[var(--error)]"
                                        />
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
                                            {formatCurrencyLocale(statement.opening_balance ?? 0, statement.currency || "SGD")}
                                        </span>
                                    </div>
                                    <div>
                                        <span className="text-muted">Closing:</span>{" "}
                                        <span>
                                            {formatCurrencyLocale(statement.closing_balance ?? 0, statement.currency || "SGD")}
                                        </span>
                                    </div>
                                    {statement.balance_validated === null || statement.balance_validated === undefined ? (
                                        <Badge variant="muted">Parsing</Badge>
                                    ) : statement.balance_validated ? (
                                        <Badge variant="success">✓ Verified</Badge>
                                    ) : (
                                        <Badge variant="warning">Needs Review</Badge>
                                    )}
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>

            <ConfirmDialog
                isOpen={deleteDialogOpen}
                onCancel={() => { setDeleteDialogOpen(false); setDeletingStatementId(null); }}
                onConfirm={handleDeleteConfirm}
                title="Delete Statement"
                message="Are you sure you want to delete this statement? This action cannot be undone."
                confirmLabel="Delete Statement"
                confirmVariant="danger"
            />
        </div>
    );
}
