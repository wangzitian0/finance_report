import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BalanceIndicator } from "@/components/statements/StatementReview";
import { TrustScoreHero } from "@/components/audit/AuditPanels";

describe("Honest empty-ledger and null-balance indicators (#2955, #3254)", () => {
  it("renders dashes and Opening Unknown when opening/closing balances are null", () => {
    render(
      <BalanceIndicator
        openingBalance={null}
        closingBalance={null}
        validationResult={null}
        currency="SGD"
      />,
    );
    expect(screen.getByText("Opening Unknown")).toBeInTheDocument();
    expect(screen.queryByText("Opening Anchored")).toBeNull();
    expect(screen.queryByText(/SGD 0\.00/)).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("renders honest non-audit-ready messaging when books are C_ATTENTION_NEEDED / empty", () => {
    render(
      <TrustScoreHero
        score={70}
        grade="C_ATTENTION_NEEDED"
        asOfDate="2026-10-01"
        currency="SGD"
      />,
    );
    expect(screen.getByText(/Grade C · Attention Needed/i)).toBeInTheDocument();
    expect(screen.getByText(/Upload statements or fix discrepancies/i)).toBeInTheDocument();
    expect(screen.queryByText(/All book checks verified/i)).toBeNull();
  });
});
