import { beforeEach, describe, it, expect, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";

import AuditPage from "@/app/(main)/audit/page";
import { apiOperation } from "@/lib/api-client";

import { setTestUrl } from "./helpers/nextNavigation";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

const mockedApiOperation = vi.mocked(apiOperation);

const HEALTH_A = {
    score: 99,
    grade: "A_AUDIT_READY",
    as_of_date: "2026-10-22",
    currency: "SGD",
    equation_invariant: { is_healthy: true, name: "Equation", summary: "Balanced", detail: "", delta: "0" },
    temporal_continuity_invariant: { is_healthy: true, name: "Continuity", summary: "Continuous", detail: "", delta: "0" },
    reconciliation_purity_invariant: { is_healthy: true, name: "Purity", summary: "Pure", detail: "", delta: "0" },
    lineage_anchors_invariant: { is_healthy: true, name: "Lineage", summary: "Traced", detail: "", delta: "0" },
    timeline: [],
    action_items: [],
};

const stats = (unmatched: number, pendingReview = 0) => ({
    total_transactions: 10,
    matched_transactions: 10 - unmatched,
    unmatched_transactions: unmatched,
    pending_review: pendingReview,
    auto_accepted: 5,
    match_rate: 70,
    score_distribution: {},
});

const workflowStatus = (primaryState: string) => ({
    primary_state: primaryState,
    next_action: { type: "resolve_blocker", count: 1, href: "/reports?tab=package", label: "Resolve blocker", summary: "" },
    report_readiness: { state: primaryState === "blocked" ? "blocked" : "ready", blocking_count: primaryState === "blocked" ? 1 : 0, href: "/reports" },
    event_counts: { unread: 0, action_required: 0, blocked: 0 },
});

function mockAuditApi(overrides: Record<string, unknown> = {}) {
    mockedApiOperation.mockImplementation((async (op: string) => {
        if (op in overrides) return overrides[op];
        if (op === "get_data_quality_health_reports_data_quality_get") throw new Error("offline");
        if (op === "reconciliation_stats_reconciliation_stats_get") return stats(0);
        return { items: [] };
    }) as never);
}

function tabs() {
    const list = screen.getByRole("tablist", { name: "Audit tabs" });
    return within(list).getAllByRole("tab");
}

function selectedTab() {
    return tabs().find((tab) => tab.getAttribute("aria-selected") === "true");
}

describe("Audit hub (EPIC-022 AC22.21.3)", () => {
    beforeEach(() => {
        mockedApiOperation.mockReset();
        mockAuditApi();
        setTestUrl("/audit");
    });

    // AC-ledger.fe-processing.5
    it("AC15.7.6 aggregates the verify-on-demand machinery as deep-linking cards", async () => {
        setTestUrl("/audit?tab=books");
        render(<AuditPage />);

        expect(screen.getByRole("heading", { name: "Audit" })).toBeInTheDocument();

        const links = [
            { name: /Reconciliation/, href: "/reconciliation" },
            { name: /Journal/, href: "/journal" },
            { name: /Statements/, href: "/upload" },
        ];
        const panel = screen.getByRole("tabpanel");
        for (const { name, href } of links) {
            expect(within(panel).getByRole("link", { name }).closest("a")).toHaveAttribute("href", href);
        }
    });

    it("renders one Needs Confirmation queue in plain language and no separate attention links", async () => {
        setTestUrl("/audit?tab=needs-you");
        render(<AuditPage />);

        const queue = screen.getByTestId("needs-confirmation-queue");
        expect(within(queue).getByRole("heading", { name: "Needs Confirmation" })).toBeInTheDocument();
        expect(screen.getAllByRole("heading", { name: "Needs Confirmation" })).toHaveLength(1);
        expect(await screen.findByRole("heading", { name: "Suggestions to review" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Low-confidence items" })).not.toBeInTheDocument();
        for (const link of screen.queryAllByRole("link")) {
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
            reconciliation_stats_reconciliation_stats_get: stats(3, 2),
            list_ai_suggestions_ai_suggestions_get: {
                items: [{ suggestion_id: "a1", transaction: "COFFEE SHOP", suggested_category_or_match: "Dining", ai_score: 72, ai_reasoning: "Merchant name", direction: "OUT" }],
            },
        });
        render(<AuditPage />);

        const queue = await screen.findByTestId("needs-confirmation-queue");
        const hrefs = (await within(queue).findAllByRole("link")).map((link) => link.getAttribute("href"));
        expect(hrefs).toEqual([
            "/reconciliation?tab=unmatched&from=attention",
            "/statements/s1?from=attention",
            "/reconciliation?from=attention",
        ]);
        expect((await screen.findAllByText("COFFEE SHOP")).length).toBeGreaterThan(0);
        expect(screen.getAllByRole("button", { name: "Accept" }).length).toBeGreaterThan(0);
        expect(screen.queryByRole("heading", { name: "Review this reconciliation run" })).not.toBeInTheDocument();
    });

    // AC-meta.fe-audit-queue.3
    it("AC-meta.fe-audit-queue.3 opens on Needs you while an item needs the user and on Health when none does", async () => {
        mockAuditApi({
            list_statements_statements_get: { items: [{ id: "s1", original_filename: "oct.csv", status: "parsed", confidence_score: 80 }] },
            reconciliation_stats_reconciliation_stats_get: stats(1),
            list_unmatched_reconciliation_unmatched_get: { items: [{ id: "t1", description: "PayNow Transfer REF 4471" }], total: 1 },
            list_ai_suggestions_ai_suggestions_get: {
                items: [{ suggestion_id: "a1", transaction: "COFFEE SHOP", suggested_category_or_match: "Dining", ai_score: 72, ai_reasoning: "Merchant", direction: "OUT" }],
            },
        });
        const view = render(<AuditPage />);

        // While the counts load, no tab is selected and no tab content shows.
        expect(selectedTab()).toBeUndefined();
        expect(screen.getByRole("status", { name: "Loading the items that need you" })).toBeInTheDocument();

        // Two queue items and one AI suggestion.
        expect(await screen.findByTestId("needs-you-count")).toHaveTextContent("3");
        expect(selectedTab()).toHaveTextContent("Needs you");
        const queue = screen.getByTestId("needs-confirmation-queue");
        expect(within(queue).getByRole("link", { name: /PayNow Transfer REF 4471/ })).toHaveAttribute(
            "href",
            "/reconciliation?tab=unmatched&from=attention",
        );
        expect(tabs().map((tab) => [tab.textContent, tab.getAttribute("href")])).toEqual([
            ["Needs you3", "/audit?tab=needs-you"],
            ["Health", "/audit?tab=health"],
            ["Books", "/audit?tab=books"],
        ]);
        view.unmount();

        // Nothing needs the user: the page opens on Health.
        mockAuditApi({ get_data_quality_health_reports_data_quality_get: HEALTH_A });
        render(<AuditPage />);
        expect(await screen.findByText("Grade A · Audit-Ready")).toBeInTheDocument();
        expect(selectedTab()).toHaveTextContent("Health");
        expect(screen.getByTestId("needs-you-count")).toHaveTextContent("0");
        expect(screen.queryByTestId("needs-confirmation-queue")).toBeNull();
    });

    // AC-meta.fe-audit-queue.3
    it("AC-meta.fe-audit-queue.3 selects the tab of the URL and keeps the run review on Needs you", async () => {
        setTestUrl("/audit?tab=health");
        render(<AuditPage />);
        expect(selectedTab()).toHaveTextContent("Health");
        expect(screen.queryByTestId("needs-confirmation-queue")).toBeNull();

        act(() => setTestUrl("/audit?run_id=run-1"));
        expect(selectedTab()).toHaveTextContent("Needs you");
        expect(screen.getByRole("heading", { name: "Review this reconciliation run" })).toBeInTheDocument();
        expect(tabs().map((tab) => tab.getAttribute("href"))).toEqual([
            "/audit?tab=needs-you&run_id=run-1",
            "/audit?tab=health&run_id=run-1",
            "/audit?tab=books&run_id=run-1",
        ]);
    });

    // AC-meta.fe-audit-queue.4
    it("AC-meta.fe-audit-queue.4 shows no audit-ready grade while an unmatched row or a blocker exists", async () => {
        const cases: [string, Record<string, unknown>, RegExp][] = [
            ["one unmatched row", { reconciliation_stats_reconciliation_stats_get: stats(1) }, /1 transaction has no ledger match/],
            ["a workflow blocker", { get_workflow_status_endpoint_workflow_status_get: workflowStatus("blocked") }, /A blocker holds your reports/],
        ];
        for (const [label, overrides, reason] of cases) {
            mockAuditApi({ get_data_quality_health_reports_data_quality_get: HEALTH_A, ...overrides });
            setTestUrl("/audit?tab=health");
            const view = render(<AuditPage />);
            expect(await screen.findByText("Open items remain"), label).toBeInTheDocument();
            expect(screen.getAllByText(reason).length, label).toBeGreaterThan(0);
            expect(screen.getByText("The checks pass. Open items remain.")).toBeInTheDocument();
            expect(screen.queryByText(/Audit[- ]Ready/i), label).toBeNull();
            view.unmount();
        }
    });
});
