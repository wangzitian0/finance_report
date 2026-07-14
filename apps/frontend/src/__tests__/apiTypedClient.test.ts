import { describe, it, expect } from "vitest";

import type { Schemas } from "@/lib/api-schema";

// AC12.28.3: high-traffic call sites are typed against the generated OpenAPI
// schema (#1004), so FE↔BE response-shape drift is caught at compile time
// (`npm run build` / tsc) rather than at runtime. These values are checked
// against the generated `Schemas[...]` aliases, so a backend contract change that
// isn't regenerated would fail the type-check.
describe("generated typed client (#1004)", () => {
    // AC-meta.fe-http-client.2
    it("test_AC12_28_3_types_stage2_batch_responses_against_generated_schema", () => {
        const approve: Schemas["BatchApproveResponse"] = {
            approved_count: 2,
            journal_entries_created: 1,
            journal_entries_reconciled: 1,
        };
        const reject: Schemas["BatchRejectResponse"] = { rejected_count: 3 };

        expect(approve.approved_count).toBe(2);
        expect(approve.journal_entries_created + approve.journal_entries_reconciled).toBe(2);
        expect(reject.rejected_count).toBe(3);
    });
});
