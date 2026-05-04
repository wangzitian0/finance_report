"use client";

import { formatCurrencyLocale } from "@/lib/currency";

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

interface BalanceIndicatorProps {
    openingBalance: string | number | null;
    closingBalance: string | number | null;
    validationResult: BalanceValidationResult | null;
    currency: string;
}

export function BalanceIndicator({
    openingBalance,
    closingBalance,
    validationResult,
    currency
}: BalanceIndicatorProps) {
    const balanceValid = validationResult?.closing_match ?? false;

    return (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-4">
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Opening Balance</div>
                <div className="text-lg font-semibold">{formatCurrencyLocale(openingBalance ?? 0, currency)}</div>
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Closing Balance</div>
                <div className="text-lg font-semibold">{formatCurrencyLocale(closingBalance ?? 0, currency)}</div>
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-1">Calculated Closing</div>
                <div className="text-lg font-semibold">
                    {formatCurrencyLocale(
                        validationResult
                            ? parseFloat(validationResult.calculated_closing)
                            : 0,
                        currency
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
                                Mismatch (Δ: {validationResult?.closing_delta || "?"})
                            </span>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
