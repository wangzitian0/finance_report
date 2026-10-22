import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import AuditPage from "@/app/(main)/audit/page";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

function mockAuditApi(overrides: Record<string, unknown> = {}) {
    mockedApiOperation.mockImplementation((async (op: string) => {
        if (op in overrides) return overrides[op];
        if (op === "get_data_quality_health_reports_data_quality_get") throw new Error("offline");
        return { items: [] };
    }) as never);
}

describe("Audit hub (EPIC-022 AC22.21.3)", () => {
    beforeEach(() => {
        mockedApiOperation.mockReset();
        mockAuditApi();
    });

    // AC-ledger.fe-processing.5
    it("AC15.7.6 aggregates the verify-on-demand machinery (incl. Processing) as deep-linking cards", () => {
        render(<AuditPage />);

        expect(screen.getByRole("heading", { name: "Audit" })).toBeInTheDocument();

        const links = [
            { name: /Reconciliation/, href: "/reconciliation" },
            { name: /Journal/, href: "/journal" },
            { name: /Statements/, href: "/upload" },
            { name: /Processing/, href: "/processing" },
        ];
        for (const { name, href } of links) {
            expect(screen.getByRole("link", { name }).closest("a")).toHaveAttribute("href", href);
        }
    });

    it("renders one Needs Confirmation queue in plain language and no separate attention links", async () => {
        render(<AuditPage />);

        const queue = screen.getByTestId("needs-confirmation-queue");
        expect(within(queue).getByRole("heading", { name: "Needs Confirmation" })).toBeInTheDocument();
        expect(screen.getAllByRole("heading", { name: "Needs Confirmation" })).toHaveLength(1);
        expect(await screen.findByRole("heading", { name: "Suggestions to review" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Low-confidence items" })).not.toBeInTheDocument();
        for (const link of screen.getAllByRole("link")) {
            expect(link.getAttribute("href")).not.toMatch(/^\/(attention|confidence|review\/ai-suggestions)/);
        }

        expect(screen.queryByText(/TraceRecord/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Stage2/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Layer-2/i)).not.toBeInTheDocument();
    });

    // AC-meta.fe-audit-queue.2
    it("shows the confirmation rows and the AI suggestions of the three old queues on this one page", async () => {
        mockAuditApi({
            list_statements_statements_get: {
                items: [{ id: "s1", original_filename: "may.pdf", status: "parsed", confidence_score: 55, balance_validated: true }],
            },
            reconciliation_stats_reconciliation_stats_get: {
                total_transactions: 10, matched_transactions: 7, unmatched_transactions: 3, pending_review: 2, auto_accepted: 5, match_rate: 70,
            },
            list_ai_suggestions_ai_suggestions_get: {
                items: [{ suggestion_id: "a1", transaction: "COFFEE SHOP", suggested_category_or_match: "Dining", ai_score: 72, ai_reasoning: "Merchant name", direction: "OUT" }],
            },
        });
        render(<AuditPage />);

        const queue = screen.getByTestId("needs-confirmation-queue");
        const hrefs = (await within(queue).findAllByRole("link")).map((link) => link.getAttribute("href"));
        expect(hrefs).toEqual([
            "/reconciliation/unmatched?from=attention",
            "/statements/s1/review?from=attention",
            "/reconciliation?from=attention",
        ]);
        expect((await screen.findAllByText("COFFEE SHOP")).length).toBeGreaterThan(0);
        expect(screen.getAllByRole("button", { name: "Accept" }).length).toBeGreaterThan(0);
        expect(screen.queryByRole("heading", { name: "Review this reconciliation run" })).not.toBeInTheDocument();
    });
});
