import { describe, expect, it } from "vitest";

import { buildAttentionItems, type AttentionSources } from "@/lib/attention";
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
  // AC-reconciliation.fe-ia-reconciliation.3
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
    expect(byId["statement:bad"]).toBe("/statements/bad");
    // `/reconciliation` alone opens Unmatched when a row is unmatched (#2646): the link names the tab.
    expect(byId["reconciliation:pending"]).toBe("/reconciliation?tab=matches");
    expect(byId["reconciliation:unmatched"]).toBe("/reconciliation?tab=unmatched");
    expect(byId["processing:stalled"]).toBe("/upload");
  });

  // AC-reconciliation.fe-ia-reconciliation.6
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

  // AC-reconciliation.fe-ia-reconciliation.10
  it("AC-reconciliation.fe-ia-reconciliation.10 names the unmatched item by its newest row", () => {
    const unmatched = (firstUnmatched: AttentionSources["firstUnmatched"], count: number) =>
      buildAttentionItems({ ...sources, stats: { ...sources.stats!, unmatched_transactions: count }, firstUnmatched }).find(
        (item) => item.kind === "unmatched_transactions",
      )!;

    expect(unmatched({ description: "PayNow Transfer REF 4471" }, 1)).toMatchObject({
      title: "PayNow Transfer REF 4471",
      detail: "1 unmatched transaction · no ledger match yet",
      href: "/reconciliation?tab=unmatched",
      confidence: 0,
    });
    expect(unmatched({ description: "  PayNow Transfer REF 4471 " }, 3)).toMatchObject({
      title: "PayNow Transfer REF 4471 and 2 more",
      detail: "3 unmatched transactions · no ledger match yet",
    });
    // Without a row description, the item keeps its count title.
    for (const row of [null, undefined, { description: "" }, { description: null }]) {
      expect(unmatched(row, 2)).toMatchObject({ title: "2 unmatched transactions", detail: "No ledger match yet" });
    }
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
});
