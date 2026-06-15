import { BankStatement } from "@/lib/types";
import { formatCurrencyLocale } from "@/lib/currency";

interface StatementSummaryCardsProps {
    statement: BankStatement;
}

export function StatementSummaryCards({ statement }: StatementSummaryCardsProps) {
    return (
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
    );
}
