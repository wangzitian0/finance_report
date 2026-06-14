import { describe, expect, it } from "vitest";

import { buildAttentionItems, summarizeTrust, type AttentionSources } from "@/lib/attention";
import type { BankStatement } from "@/lib/types";

function statement(overrides: Partial<BankStatement>): BankStatement {
  return {
    id: "s1",
    user_id: "u1",
    file_path: "/x",
    original_filename: "stmt.pdf",
    institution: "DBS",
    status: "parsed",
    confidence_score: 90,
    balance_validated: true,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    transactions: [],
    ...overrides,
  } as BankStatement;
}

const sources: AttentionSources = {
  statements: [
    statement({ id: "ok", original_filename: "ok.pdf", confidence_score: 90, balance_validated: true }),
    statement({ id: "bad", original_filename: "bad.pdf", confidence_score: 88, balance_validated: false }),
    statement({ id: "approved", status: "approved" }),
  ],
  stats: {
    total_transactions: 100,
    matched_transactions: 80,
    unmatched_transactions: 5,
    pending_review: 3,
    auto_accepted: 70,
    match_rate: 80,
    score_distribution: {},
  },
  processing: [
    { entry_id: "p1", from_account: "A", to_account: "B", amount: "100", currency: "SGD", initiated_date: "2026-01-01", days_outstanding: 9, description: "transfer" },
    { entry_id: "p2", from_account: "A", to_account: "B", amount: "50", currency: "SGD", initiated_date: "2026-05-01", days_outstanding: 2, description: "fresh" },
  ],
};

describe("attention model (EPIC-022 AC22.6)", () => {
  it("AC22.6.1 folds the open attention sources into one list sorted by ascending confidence", () => {
    const items = buildAttentionItems(sources);

    // Approved statement and the fresh (<7d) transfer are not attention items.
    expect(items.map((i) => i.id)).toEqual([
      "reconciliation:unmatched", // confidence 0
      "processing:stalled", // 30
      "statement:bad", // min(88,40)=40 (balance failed)
      "reconciliation:pending", // 80
      "statement:ok", // 90
    ]);
    // Ascending confidence.
    const confidences = items.map((i) => i.confidence);
    expect(confidences).toEqual([...confidences].sort((a, b) => a - b));
  });

  it("AC22.6.1 every item deep-links to the surface where the user can act", () => {
    const byId = Object.fromEntries(buildAttentionItems(sources).map((i) => [i.id, i.href]));
    expect(byId["statement:bad"]).toBe("/statements/bad/review");
    expect(byId["reconciliation:pending"]).toBe("/review");
    expect(byId["reconciliation:unmatched"]).toBe("/reconciliation/unmatched");
    expect(byId["processing:stalled"]).toBe("/processing");
  });

  it("AC22.11.2 every item explains why it was flagged", () => {
    const items = buildAttentionItems(sources);
    const byId = Object.fromEntries(items.map((i) => [i.id, i.reason]));
    // Every surfaced item carries a non-trivial, plain-language reason.
    for (const item of items) {
      expect(item.reason.length).toBeGreaterThan(20);
    }
    // The reason is contextual, not boilerplate: a failed-balance statement
    // reads differently from a clean parsed one.
    expect(byId["statement:bad"]).toMatch(/balance/i);
    expect(byId["statement:bad"]).not.toBe(byId["statement:ok"]);
    expect(byId["reconciliation:unmatched"]).toMatch(/no matching ledger/i);
  });

  it("AC22.6.1 is empty when everything is reconciled and approved", () => {
    expect(
      buildAttentionItems({
        statements: [statement({ status: "approved" })],
        stats: { total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} },
        processing: [],
      }),
    ).toEqual([]);
  });

  it("AC22.6.2 summarizes trust into trusted / needs-confirmation / low-confidence buckets", () => {
    const items = buildAttentionItems(sources);
    const summary = summarizeTrust(items, sources.stats);
    expect(summary.trusted).toBe(80);
    expect(summary.needsConfirmation).toBe(items.length);
    // unmatched(0), processing(30), statement:bad(40) are below the 50 threshold.
    expect(summary.lowConfidence).toBe(3);
  });
});
