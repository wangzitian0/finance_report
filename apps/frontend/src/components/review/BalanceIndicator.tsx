"use client";

import { formatCurrencyLocale } from "@/lib/audit/money";
import type { MoneyValue } from "@/lib/types";

interface BalanceValidationResult {
    opening_balance: string;
    // null when the statement has no declared closing balance (#1390).
    closing_balance: string | null;
    calculated_closing: string;
    opening_delta: string;
    closing_delta: string;
    opening_match: boolean;
    closing_match: boolean;
    validated_at: string;
}

interface BalanceIndicatorProps {
    openingBalance: MoneyValue | null;
    closingBalance: MoneyValue | null;
    validationResult: BalanceValidationResult | null;
    currency: string;
}

export function BalanceIndicator({
    openingBalance,
    closingBalance,
    validationResult,
    currency
}: BalanceIndicatorProps) {
    const openingValid = validationResult?.opening_match ?? false;
    const closingValid = validationResult?.closing_match ?? false;
    // #1390: a missing closing balance is "unknown", not a mismatch. Only treat
    // it as a mismatch when a closing balance was actually declared.
    const closingKnown = (validationResult?.closing_balance ?? null) !== null;

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
                            ? validationResult.calculated_closing
                            : 0,
                        currency
                    )}
                </div>
            </div>
            <div className="card p-4">
                <div className="text-xs text-muted mb-2">Balance Validation</div>
                <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                        <span className={`text-sm font-medium ${openingValid ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                            Opening {openingValid ? "Valid" : "Mismatch"}
                        </span>
                        <span className="text-xs text-muted">Opening Δ: {validationResult?.opening_delta || "?"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                        <span className={`text-sm font-medium ${!closingKnown ? "text-muted" : closingValid ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                            Closing {!closingKnown ? "Unknown" : closingValid ? "Valid" : "Mismatch"}
                        </span>
                        <span className="text-xs text-muted">Closing Δ: {validationResult?.closing_delta || "?"}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
