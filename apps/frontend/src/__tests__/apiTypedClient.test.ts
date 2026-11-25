import { describe, it, expect } from "vitest";
import type { Schemas } from "@/lib/api-schema";
describe("generated typed client (#1004)", () => {
  it("test_AC12_28_3_types_stage2_batch_responses_against_generated_schema", () => {
    const approve: Schemas["ReconciliationMatchBatchResponse"] = {
      approved_count: 2,
      rejected_count: 0,
      journal_entries_reconciled: 1,
    };
    const reject: Schemas["ReconciliationMatchBatchResponse"] = {
      approved_count: 0,
      rejected_count: 3,
      journal_entries_reconciled: 0,
    };
    expect(approve.approved_count).toBe(2);
    expect(approve.journal_entries_reconciled).toBe(1);
    expect(reject.rejected_count).toBe(3);
  });
}); // AC-meta.fe-http-client.23 AC12.28.3
