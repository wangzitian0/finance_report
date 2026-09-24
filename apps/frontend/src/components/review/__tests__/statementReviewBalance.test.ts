import { describe, expect, it } from "vitest";
import {
  calculateEffectiveBalanceValidation,
  type BalanceValidationResult,
  type ReviewBalanceTransaction,
} from "../statementReviewBalance";

describe("statementReviewBalance", () => {
  const baseOriginalResult: BalanceValidationResult = {
    opening_balance: "100.00",
    closing_balance: "130.00",
    calculated_closing: "130.00",
    opening_delta: "0.00",
    closing_delta: "0.00",
    opening_match: true,
    closing_match: true,
    validated_at: "2026-09-24T00:00:00Z",
  };

  it("returns null if originalResult is null", () => {
    expect(calculateEffectiveBalanceValidation(null, "100.00", "130.00", [])).toBeNull();
  });

  it("calculates accurate closing balance and closing match when transactions balance", () => {
    const txns: ReviewBalanceTransaction[] = [
      { amount: "50.00", direction: "IN" },
      { amount: "20.00", direction: "OUT" },
    ];

    const result = calculateEffectiveBalanceValidation(
      baseOriginalResult,
      "100.00",
      "130.00",
      txns,
    );

    expect(result).not.toBeNull();
    expect(result?.calculated_closing).toBe("130.00");
    expect(result?.closing_delta).toBe("0.00");
    expect(result?.closing_match).toBe(true);
  });

  it("calculates delta and marks closing_match false on imbalance", () => {
    const txns: ReviewBalanceTransaction[] = [
      { amount: "50.00", direction: "IN" },
      { amount: "10.00", direction: "OUT" },
    ];

    const result = calculateEffectiveBalanceValidation(
      baseOriginalResult,
      "100.00",
      "130.00",
      txns,
    );

    expect(result?.calculated_closing).toBe("140.00");
    expect(result?.closing_delta).toBe("10.00");
    expect(result?.closing_match).toBe(false);
  });

  it("avoids binary floating-point roundoff errors (e.g. 19.99 + 0.01)", () => {
    const txns: ReviewBalanceTransaction[] = [
      { amount: "19.99", direction: "IN" },
      { amount: "0.01", direction: "IN" },
      { amount: "10.10", direction: "OUT" },
      { amount: "0.20", direction: "OUT" },
    ];

    const result = calculateEffectiveBalanceValidation(
      baseOriginalResult,
      "0.00",
      "9.70",
      txns,
    );

    expect(result?.calculated_closing).toBe("9.70");
    expect(result?.closing_delta).toBe("0.00");
    expect(result?.closing_match).toBe(true);
  });

  it("handles null or undefined declared closing balance gracefully", () => {
    const txns: ReviewBalanceTransaction[] = [
      { amount: "25.50", direction: "IN" },
    ];

    const result = calculateEffectiveBalanceValidation(
      baseOriginalResult,
      "50.00",
      null,
      txns,
    );

    expect(result?.calculated_closing).toBe("75.50");
    expect(result?.closing_delta).toBe("0.00");
    expect(result?.closing_match).toBe(true);
  });
});
