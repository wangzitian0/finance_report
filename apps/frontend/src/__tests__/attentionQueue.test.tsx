import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NeedsConfirmationQueue } from "@/components/audit/NeedsConfirmationQueue";
import { apiOperation } from "@/lib/api-client";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

function mockSources({
  statements = [],
  stats = null,
  processing = [],
}: {
  statements?: unknown[];
  stats?: unknown;
  processing?: unknown[];
}) {
  mockedApiOperation.mockImplementation((operationId: any) => {
    if (operationId === "list_statements_statements_get") return Promise.resolve({ items: statements, total: statements.length } as any);
    if (operationId === "reconciliation_stats_reconciliation_stats_get") return Promise.resolve(stats as any);
    if (operationId === "list_processing_pending_accounts_processing_pending_get") return Promise.resolve({ items: processing, total: processing.length } as any);
    return Promise.resolve(null as any);
  });
}

describe("Attention queue (EPIC-022 AC22.6)", () => {
  beforeEach(() => mockedApiOperation.mockReset());


  // AC-reconciliation.fe-ia-reconciliation.7 / AC-reconciliation.fe-ia-reconciliation.8
  it("AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links", async () => {
    mockSources({
      statements: [
        { id: "bad", original_filename: "bad.pdf", status: "parsed", confidence_score: 88, balance_validated: false, transactions: [] },
      ],
      stats: { total_transactions: 100, matched_transactions: 80, unmatched_transactions: 5, pending_review: 3, auto_accepted: 70, match_rate: 80, score_distribution: {} },
      processing: [],
    });

    render(<NeedsConfirmationQueue />);

    const rows = await screen.findAllByRole("link");
    // Unmatched (confidence 0) comes before the parsed statement (40) before pending review (80).
    expect(rows[0]).toHaveAttribute("href", "/reconciliation?tab=unmatched&from=attention");
    expect(rows[1]).toHaveAttribute("href", "/statements/bad?from=attention");
    expect(rows[2]).toHaveAttribute("href", "/reconciliation?tab=matches&from=attention");

    expect(within(rows[1]).getByText("bad.pdf")).toBeInTheDocument();
    expect(within(rows[0]).getByText("0% confidence")).toBeInTheDocument();

    // AC22.11.2: each row explains *why* it was flagged, not just a score.
    const unmatchedReason = within(rows[0]).getByText(/no matching ledger entry/i);
    expect(unmatchedReason).toBeInTheDocument();
    expect(unmatchedReason).toHaveClass("text-muted");
    expect(unmatchedReason.className).not.toContain("text-muted/80");
    expect(within(rows[1]).getByText(/balance didn't reconcile/i)).toBeInTheDocument();
  });

  it("AC22.6.1 shows an all-clear empty state when nothing needs attention", async () => {
    mockSources({
      statements: [{ id: "x", original_filename: "ok.pdf", status: "approved", transactions: [] }],
      stats: { total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} },
      processing: [],
    });

    render(<NeedsConfirmationQueue />);

    await waitFor(() => expect(screen.getByText("All clear")).toBeInTheDocument());
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("AC22.6.1 surfaces a retryable error state when the sources fail to load", async () => {
    mockedApiOperation.mockImplementation((operationId: any) =>
      operationId === "list_statements_statements_get"
        ? Promise.reject(new Error("offline"))
        : Promise.resolve(null as any),
    );

    render(<NeedsConfirmationQueue />);

    await waitFor(() => expect(screen.getByText("Couldn't load the items that need confirmation")).toBeInTheDocument());
    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("AC22.6.1 Retry refetches only the failed source and then shows its items", async () => {
    let statementReads = 0;
    mockedApiOperation.mockImplementation((operationId: any) => {
      if (operationId === "list_statements_statements_get") {
        statementReads += 1;
        if (statementReads === 1) return Promise.reject(new Error("offline"));
        return Promise.resolve({
          items: [{ id: "late", original_filename: "late.pdf", status: "parsed", confidence_score: 55, balance_validated: true, transactions: [] }],
          total: 1,
        } as any);
      }
      if (operationId === "reconciliation_stats_reconciliation_stats_get") {
        return Promise.resolve({ total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} } as any);
      }
      return Promise.resolve({ items: [], total: 0 } as any);
    });

    render(<NeedsConfirmationQueue />);

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    const row = await screen.findByRole("link", { name: /late\.pdf/ });
    expect(row).toHaveAttribute("href", "/statements/late?from=attention");
    expect(screen.queryByText("Couldn't load the items that need confirmation")).not.toBeInTheDocument();
    const reads = (operationId: string) =>
      mockedApiOperation.mock.calls.filter(([calledId]) => calledId === operationId).length;
    expect(reads("list_statements_statements_get")).toBe(2);
    expect(reads("reconciliation_stats_reconciliation_stats_get")).toBe(1);
    expect(reads("list_processing_pending_accounts_processing_pending_get")).toBe(1);
  });
});
