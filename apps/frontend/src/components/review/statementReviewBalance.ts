import Decimal from "decimal.js";
import { formatAmount, isAmountZero } from "@/lib/audit/money";

export interface BalanceValidationResult {
  opening_balance: string;
  closing_balance: string | null;
  calculated_closing: string;
  opening_delta: string;
  closing_delta: string;
  opening_match: boolean;
  closing_match: boolean;
  validated_at: string;
}

export interface ReviewBalanceTransaction {
  amount: string;
  direction: "IN" | "OUT" | string;
}

/**
 * Decimal-safe statement review balance calculation.
 *
 * Replaces legacy float-based toCents/parseFloat math in statement review page
 * to comply with the project red line: NEVER use float for monetary amounts.
 */
export function calculateEffectiveBalanceValidation(
  originalResult: BalanceValidationResult | null,
  openingBalance: string | null | undefined,
  declaredClosingBalance: string | null | undefined,
  transactions: ReviewBalanceTransaction[],
): BalanceValidationResult | null {
  if (!originalResult) return null;

  const safeDecimal = (val: string | null | undefined): Decimal => {
    if (!val || typeof val !== "string" || val.trim() === "") return new Decimal(0);
    try {
      return new Decimal(val.trim());
    } catch {
      return new Decimal(0);
    }
  };

  const openingDec = safeDecimal(openingBalance);
  let netDec = new Decimal(0);

  for (const txn of transactions) {
    const amtDec = safeDecimal(txn.amount);
    if (txn.direction === "IN") {
      netDec = netDec.plus(amtDec);
    } else {
      netDec = netDec.minus(amtDec);
    }
  }

  const calculatedClosing = openingDec.plus(netDec);
  let closingDelta = "0.00";
  let closingMatch = true;

  if (
    declaredClosingBalance !== null &&
    declaredClosingBalance !== undefined &&
    typeof declaredClosingBalance === "string" &&
    declaredClosingBalance.trim() !== ""
  ) {
    const declaredClosing = safeDecimal(declaredClosingBalance);
    const delta = calculatedClosing.minus(declaredClosing);
    closingDelta = formatAmount(delta, 2);
    closingMatch = isAmountZero(delta);
  }

  return {
    ...originalResult,
    calculated_closing: formatAmount(calculatedClosing, 2),
    closing_delta: closingDelta,
    closing_match: closingMatch,
  };
}
