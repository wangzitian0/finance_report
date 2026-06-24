import Link from "next/link";

import { BankStatement } from "@/lib/types";
import { StatusBadge } from "@/components/ui";

interface StatementHeaderProps {
    statement: BankStatement;
    statementId: string;
    canImport: boolean;
    canRetry: boolean;
    importLoading: boolean;
    retryLoading: boolean;
    onBrokerageImport: () => void;
    onRetry: () => void;
    formatCode: (currency?: string | null) => string;
    formatPeriod: (start?: string | null, end?: string | null) => string;
}

export function StatementHeader({
    statement,
    statementId,
    canImport,
    canRetry,
    importLoading,
    retryLoading,
    onBrokerageImport,
    onRetry,
    formatCode,
    formatPeriod,
}: StatementHeaderProps) {
    return (
        <div className="page-header flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 mb-2">
                    <h1 className="page-title truncate">{statement.original_filename}</h1>
                    <StatusBadge
                        status={statement.status}
                        variants={{ approved: "success", rejected: "error", parsed: "warning" }}
                    />
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
            </div>
        </div>
    );
}
