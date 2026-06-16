"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { useToast } from "@/components/ui/Toast";
import { FlowStepBanner } from "@/components/workflow/FlowStepBanner";
import { apiFetch } from "@/lib/api";
import { BankStatement, BrokerageImportResponse } from "@/lib/types";
import { StatementHeader } from "./_components/StatementHeader";
import { BrokerageImportResultBanner } from "./_components/BrokerageImportResultBanner";
import { StatementSummaryCards } from "./_components/StatementSummaryCards";
import { StatementTransactionsTable } from "./_components/StatementTransactionsTable";

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

            <div className="mb-6">
                <FlowStepBanner current="review" />
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
            <StatementHeader
                statement={statement}
                statementId={statementId}
                canImport={canImport}
                canRetry={canRetry}
                importLoading={importLoading}
                retryLoading={retryLoading}
                onBrokerageImport={handleBrokerageImport}
                onRetry={handleRetry}
                formatCode={formatCode}
                formatPeriod={formatPeriod}
            />

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
            {importResult && <BrokerageImportResultBanner importResult={importResult} />}

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
            <StatementSummaryCards statement={statement} />

            {/* Transactions Table */}
            <StatementTransactionsTable statement={statement} />
        </div>
    );
}
