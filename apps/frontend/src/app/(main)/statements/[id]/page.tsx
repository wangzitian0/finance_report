"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { BankStatement, BankStatementTransaction, BrokerageImportResponse } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/currency";

const PARSING_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export default function StatementDetailPage() {
    const { showToast } = useToast();
    const params = useParams();
    const searchParams = useSearchParams();
    const statementId = params.id as string;
    const approvedRedirect = searchParams.get("approved") === "1";
    const entriesCreated = Number(searchParams.get("entriesCreated")) || 0;

    const [statement, setStatement] = useState<BankStatement | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [retryLoading, setRetryLoading] = useState(false);
    const [polling, setPolling] = useState(false);
    const [consecutiveErrors, setConsecutiveErrors] = useState(0);
    const [pollingStoppedReason, setPollingStoppedReason] = useState<string | null>(null);
    const [parsingStartTime, setParsingStartTime] = useState<number | null>(null);
    const [importResult, setImportResult] = useState<BrokerageImportResponse | null>(null);
    const [importError, setImportError] = useState<string | null>(null);
    const [importLoading, setImportLoading] = useState(false);
    const approvedNow = approvedRedirect && statement?.status === "approved";

    const fetchStatement = useCallback(async () => {
        try {
            const data = await apiFetch<BankStatement>(`/api/statements/${statementId}`);
            setStatement(data);
            setError(null);
            setConsecutiveErrors(0);
            
            if (data.status === "parsing") {
                setPolling(true);
                setParsingStartTime((prev) => prev ?? Date.now());
            } else {
                setPolling(false);
                setParsingStartTime(null);
            }
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
        setParsingStartTime(Date.now());
        setPolling(true);
        fetchStatement();
    }, [fetchStatement]);

    useEffect(() => {
        fetchStatement();
    }, [fetchStatement]);

    // Auto-refresh while parsing (with timeout)
    useEffect(() => {
        if (!polling) return;

        const interval = setInterval(() => {
            if (parsingStartTime && Date.now() - parsingStartTime > PARSING_TIMEOUT_MS) {
                setPolling(false);
                setParsingStartTime(null);
                setPollingStoppedReason(
                    "Parsing has been running for over 5 minutes. It may be stuck. You can retry parsing with a different model."
                );
                showToast("Parsing appears stuck — stopped auto-refresh", "error");
                return;
            }
            fetchStatement();
        }, 3000);
        return () => {
            clearInterval(interval);
        };
    }, [polling, fetchStatement, parsingStartTime, showToast]);

    const handleRetry = async () => {
        setRetryLoading(true);
        setParsingStartTime(null);
        setPollingStoppedReason(null);
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

    const handleBrokerageImport = async () => {
        setImportLoading(true);
        setImportError(null);
        setImportResult(null);
        try {
            const result = await apiFetch<BrokerageImportResponse>(
                `/api/statements/${statementId}/brokerage/import`,
                { method: "POST" },
            );
            setImportResult(result);
            showToast("Brokerage positions imported successfully", "success");
        } catch (err) {
            // Surface a safe, actionable message — never expose raw credentials or
            // internal storage paths returned by the server.
            const raw = err instanceof Error ? err.message : "Import failed";
            const safe = raw.replace(/https?:\/\/\S+/g, "[URL]").replace(/s3:\/\/\S+/g, "[URL]");
            setImportError(safe);
            showToast("Brokerage import failed", "error");
        } finally {
            setImportLoading(false);
        }
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

    const canRetry = statement.status === "parsed" || statement.status === "rejected" || (statement.status === "parsing" && Boolean(pollingStoppedReason));
    const canImport = !importResult && (statement.status === "parsed" || statement.status === "approved");

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
                            onClick={handleBrokerageImport}
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
                </div>
            </div>

            {approvedNow && (
                <div className="mb-4 p-4 border border-[var(--success)]/30 bg-[var(--success-muted)] rounded-lg">
                    <p className="font-medium text-[var(--success)]">Statement approved. {entriesCreated} journal entries created.</p>
                    <div className="mt-2 flex items-center gap-2">
                        <Link href="/journal" className="btn-secondary text-sm">View in Journal</Link>
                        <Link href="/reports" className="btn-secondary text-sm">Go to Reports</Link>
                    </div>
                </div>
            )}

            {/* Brokerage Import Result */}
            {importResult && (
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
            )}

            {/* Brokerage Import Error */}
            {importError && (
                <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg" data-testid="import-error-banner">
                    <div className="flex items-start gap-3">
                        <svg className="w-5 h-5 text-[var(--error)] flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <div className="flex-1 min-w-0">
                            <div className="font-medium text-[var(--error)] mb-1">Brokerage Import Failed</div>
                            <div className="text-sm text-[var(--foreground-muted)] mb-3">{importError}</div>
                            <button
                                onClick={handleBrokerageImport}
                                disabled={importLoading}
                                className="btn-secondary text-sm"
                            >
                                Retry Import
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Error */}
            {error && (
                <div className="mb-4 alert-error">
                    {error}
                </div>
            )}

            {/* Parsing Progress Indicator (indeterminate) */}
            {polling && (
                <div className="mb-4 card p-4">
                    <div
                        className="flex items-center gap-3"
                        role="status"
                        aria-live="polite"
                        aria-busy="true"
                    >
                        <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                        <div className="flex-1">
                            <div className="text-sm font-medium text-[var(--accent)]">
                                Parsing in progress…
                            </div>
                            <div className="text-xs text-muted mt-0.5">
                                AI is extracting transaction data. This may take up to 3 minutes.
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Rejected Status Alert */}
            {statement.status === "rejected" && (
                <div className="mb-4 p-4 border border-[var(--error)]/30 bg-[var(--error-muted)] rounded-lg">
                    <div className="flex items-start gap-3">
                        <svg className="w-5 h-5 text-[var(--error)] flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-label="Error">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <div className="flex-1 min-w-0">
                            <div className="font-medium text-[var(--error)] mb-1">Parsing Failed</div>
                            {statement.validation_error && (
                                <div className="text-sm text-[var(--foreground-muted)] mb-3 break-words">{statement.validation_error}</div>
                            )}
                            <button 
                                type="button"
                                onClick={handleRetry}
                                disabled={retryLoading}
                                className="btn-secondary text-sm"
                            >
                                {retryLoading ? "Retrying..." : "Retry Parse"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Summary Cards */}
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
        </div>
    );
}
