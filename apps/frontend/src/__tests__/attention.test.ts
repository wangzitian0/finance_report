import { expect, it } from "vitest";
import { buildAttentionItems, type AttentionSources } from "@/lib/attention";
const E = expect;
const stats = (unmatched_transactions = 5, pending_review = 3) => ({
  total_transactions: 100,
  matched_transactions: 80,
  unmatched_transactions,
  pending_review,
  auto_accepted: 70,
  match_rate: 80,
  score_distribution: {},
});
const src: AttentionSources = {
  statements: [
    {
      id: "ok",
      original_filename: "ok.pdf",
      status: "parsed",
      confidence_score: 90,
      balance_validated: true,
    },
    {
      id: "bad",
      original_filename: "bad.pdf",
      status: "parsed",
      confidence_score: 88,
      balance_validated: false,
    },
    { id: "ap", original_filename: "a.pdf", status: "approved" },
  ],
  stats: stats(),
  processing: [{ days_outstanding: 9 }, { days_outstanding: 2 }] as any,
};
it("AC22.6.1 AC22.11.2 AC-reconciliation.fe-ia-reconciliation.10 attention", () => {
  const items = buildAttentionItems(src),
    byId = Object.fromEntries(items.map((i) => [i.id, i]));
  E(items.map((i) => i.id)).toEqual([
    "reconciliation:unmatched",
    "processing:stalled",
    "statement:bad",
    "reconciliation:pending",
    "statement:ok",
  ]);
  E(items.map((i) => i.confidence)).toEqual(
    [...items.map((i) => i.confidence)].sort((a, b) => a - b),
  );
  E([
    byId["statement:bad"].href,
    byId["reconciliation:pending"].href,
    byId["reconciliation:unmatched"].href,
    byId["processing:stalled"].href,
  ]).toEqual([
    "/statements/bad",
    "/reconciliation?tab=matches",
    "/reconciliation?tab=unmatched",
    "/upload",
  ]);
  for (const i of items) E(i.reason.length).toBeGreaterThan(20);
  E(byId["statement:bad"].reason).toMatch(/balance/i);
  E(byId["statement:bad"].reason).not.toBe(byId["statement:ok"].reason);
  E(byId["reconciliation:unmatched"].reason).toMatch(/no matching ledger/i);
  const unm = (firstUnmatched: AttentionSources["firstUnmatched"], n: number) =>
    buildAttentionItems({ ...src, stats: stats(n), firstUnmatched }).find(
      (i) => i.kind === "unmatched_transactions",
    )!;
  E(unm({ description: "PayNow 4471" }, 1)).toMatchObject({
    title: "PayNow 4471",
    detail: "1 unmatched transaction · no ledger match yet",
    href: "/reconciliation?tab=unmatched",
    confidence: 0,
  });
  E(unm({ description: "  PayNow 4471 " }, 3)).toMatchObject({
    title: "PayNow 4471 and 2 more",
    detail: "3 unmatched transactions · no ledger match yet",
  });
  for (const row of [
    null,
    undefined,
    { description: "" },
    { description: null },
  ])
    E(unm(row, 2)).toMatchObject({
      title: "2 unmatched transactions",
      detail: "No ledger match yet",
    });
  E(
    buildAttentionItems({
      statements: [{ id: "a", original_filename: "a.pdf", status: "approved" }],
      stats: stats(0, 0),
      processing: [],
    }),
  ).toEqual([]);
});
// AC-reconciliation.fe-ia-reconciliation.3 AC-reconciliation.fe-ia-reconciliation.6
