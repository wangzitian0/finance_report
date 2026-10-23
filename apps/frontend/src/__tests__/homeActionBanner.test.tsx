import { act, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HomeActionBanner, pickHomeAction } from "@/components/home/HomeActionBanner";
import { apiOperation } from "@/lib/api-client";
import type { AttentionItem } from "@/lib/attention";
import type { WorkflowStatusResponse } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

function mockSources(stats: unknown, statements: unknown[] = [], processing: unknown[] = [], unmatched: unknown[] = []) {
  mockedApiOperation.mockImplementation(((operationId: string) => {
    if (operationId === "list_statements_statements_get") return Promise.resolve({ items: statements, total: statements.length });
    if (operationId === "reconciliation_stats_reconciliation_stats_get") return Promise.resolve(stats);
    if (operationId === "list_processing_pending_accounts_processing_pending_get") return Promise.resolve({ items: processing, total: processing.length });
    if (operationId === "list_unmatched_reconciliation_unmatched_get") return Promise.resolve({ items: unmatched, total: unmatched.length });
    return Promise.resolve(null);
  }) as never);
}

const status = (primary_state: WorkflowStatusResponse["primary_state"]): WorkflowStatusResponse =>
  ({
    primary_state,
    next_action: { type: "review_required", count: 1, href: "/audit", label: "Review required", summary: "Confirm the source." },
    report_readiness: { state: "none", blocking_count: 0, href: "/reports" },
    event_counts: { unread: 0, action_required: 1, blocked: 0 },
  }) as WorkflowStatusResponse;

describe("Home action banner (#2621 LC, EPIC-022 AC22.6.2)", () => {
  beforeEach(() => mockedApiOperation.mockReset());

  it("AC22.6.2 shows the confirmation count of the attention sources and links to the /audit queue", async () => {
    mockSources(
      { total_transactions: 100, matched_transactions: 80, unmatched_transactions: 5, pending_review: 3, auto_accepted: 70, match_rate: 80, score_distribution: {} },
    );

    render(<HomeActionBanner />);

    // unmatched (1 item) + pending review (1 item) = 2 needing confirmation.
    const banner = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(banner).getByRole("heading", { name: "2 items need you" })).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: "Open Needs you" })).toHaveAttribute("href", "/audit?tab=needs-you");
  });

  // AC-reporting.fe-period-cockpit.9
  it("AC-reporting.fe-period-cockpit.9 names the count and the first item of the queue before a workflow blocker", async () => {
    // The data of the #2646 review: one unmatched row, a brokerage file at 20 % and a statement at 80 %,
    // while the report package is blocked.
    mockSources(
      { total_transactions: 26, matched_transactions: 25, unmatched_transactions: 1, pending_review: 0, auto_accepted: 25, match_rate: 96, score_distribution: {} },
      [
        { id: "s-oct", status: "parsed", original_filename: "october.csv", confidence_score: 80, balance_validated: true },
        { id: "s-ibkr", status: "parsed", original_filename: "ibkr.csv", confidence_score: 20, balance_validated: true },
      ],
      [],
      [{ id: "t1", description: "PayNow Transfer REF 4471" }],
    );
    const blocked = status("blocked");
    const baseImplementation = mockedApiOperation.getMockImplementation()!;
    mockedApiOperation.mockImplementation(((operationId: string, request: unknown) =>
      operationId === "get_workflow_status_endpoint_workflow_status_get"
        ? Promise.resolve(blocked)
        : baseImplementation(operationId as never, request as never)) as never);

    render(<HomeActionBanner />);

    const banner = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(banner).getByRole("heading", { name: "3 items need you" })).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: "PayNow Transfer REF 4471" })).toHaveAttribute(
      "href",
      "/reconciliation?tab=unmatched&from=attention",
    );
    expect(banner).toHaveTextContent("1 unmatched transaction · no ledger match yet");
    expect(within(banner).queryByText("A blocker holds your reports")).toBeNull();
    expect(mockedApiOperation).toHaveBeenCalledWith("list_unmatched_reconciliation_unmatched_get", { query: { limit: 1 } });
  });

  it("AC22.6.2 stays silent when nothing needs attention", async () => {
    mockSources(
      { total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} },
    );

    const { container } = render(<HomeActionBanner />);

    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("list_processing_pending_accounts_processing_pending_get", expect.anything()));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("AC22.6.2 stays silent (no crash) when the sources fail to load", async () => {
    mockedApiOperation.mockImplementation(((operationId: string) =>
      operationId === "list_statements_statements_get" ? Promise.reject(new Error("offline")) : Promise.resolve(null)) as never);

    const { container } = render(<HomeActionBanner />);

    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("list_statements_statements_get", expect.anything()));
    // Let the rejected source settle: the banner must stay empty after the failure, not only while it loads.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(container).toBeEmptyDOMElement();
  });

  // AC-platform.fe-workflow.5
  it("AC-platform.fe-workflow.5 shows the next-action summary, and the workflow-state sentence once when the summary is empty", async () => {
    const withSummary = status("needs_action");
    const withoutSummary = { ...withSummary, next_action: { ...withSummary.next_action, summary: "" } };
    const mockStatus = (workflow: WorkflowStatusResponse) =>
      mockedApiOperation.mockImplementation(((operationId: string) =>
        Promise.resolve(operationId === "get_workflow_status_endpoint_workflow_status_get" ? workflow : null)) as never);

    mockStatus(withSummary);
    const { unmount } = render(<HomeActionBanner />);
    const banner = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(banner).getByText("Confirm the source.")).toBeInTheDocument();
    expect(within(banner).queryByText("Review the required action so automation can continue.")).not.toBeInTheDocument();
    unmount();

    mockStatus(withoutSummary);
    render(<HomeActionBanner />);
    const fallbackBanner = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(fallbackBanner).getAllByText("Review the required action so automation can continue.")).toHaveLength(1);
    expect(within(fallbackBanner).getByRole("link", { name: "Review required" })).toHaveAttribute("href", "/audit");
  });

  // AC-reporting.fe-period-cockpit.6
  it("AC-reporting.fe-period-cockpit.6 picks at most one action: the queue first, then the workflow, then the first upload", () => {
    const item = (id: string, title: string, href: string): AttentionItem => ({
      id, kind: "statement_review", title, detail: "Parsed — ready to review", reason: "", confidence: 20, href,
    });
    const queue = [item("statement:a", "ibkr.csv", "/statements/a"), item("statement:b", "october.csv", "/statements/b")];
    for (const state of ["blocked", "needs_action", "empty", "ready", "processing"] as const) {
      expect(pickHomeAction(status(state), queue), state).toMatchObject({
        title: "2 items need you",
        href: "/audit?tab=needs-you",
        firstItem: { title: "ibkr.csv", detail: "Parsed — ready to review", href: "/statements/a?from=attention" },
      });
    }
    expect(pickHomeAction(null, queue.slice(0, 1))).toMatchObject({ title: "1 item needs you" });
    expect(pickHomeAction(status("blocked"), [])).toMatchObject({ title: "A blocker holds your reports", cta: "Review required", href: "/audit" });
    expect(pickHomeAction(status("needs_action"), [])).toMatchObject({ title: "An item needs your review", summary: "Confirm the source." });
    expect(pickHomeAction(status("empty"), [])).toMatchObject({ title: "Upload your first statement", href: "/upload" });
    expect(pickHomeAction(status("ready"), [])).toBeNull();
    expect(pickHomeAction(status("processing"), [])).toBeNull();
    expect(pickHomeAction(null, [])).toBeNull();
  });
});
