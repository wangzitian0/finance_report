import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AttentionPage from "@/app/(main)/attention/page";
import { apiFetch } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);

function mockSources({
  statements = [],
  stats = null,
  processing = [],
}: {
  statements?: unknown[];
  stats?: unknown;
  processing?: unknown[];
}) {
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/statements") return Promise.resolve({ items: statements, total: statements.length });
    if (path === "/api/reconciliation/stats") return Promise.resolve(stats);
    if (path === "/api/accounts/processing/pending") return Promise.resolve({ items: processing, total: processing.length });
    return Promise.resolve(null);
  });
}

describe("Attention queue (EPIC-022 AC22.6)", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("AC22.6.1 renders the open attention items lowest-confidence first, each deep-linking to its action surface", async () => {
    mockSources({
      statements: [
        { id: "bad", original_filename: "bad.pdf", status: "parsed", confidence_score: 88, balance_validated: false, transactions: [] },
      ],
      stats: { total_transactions: 100, matched_transactions: 80, unmatched_transactions: 5, pending_review: 3, auto_accepted: 70, match_rate: 80, score_distribution: {} },
      processing: [],
    });

    render(<AttentionPage />);

    const rows = await screen.findAllByRole("link");
    // Unmatched (confidence 0) comes before the parsed statement (40) before pending review (80).
    expect(rows[0]).toHaveAttribute("href", "/reconciliation/unmatched");
    expect(rows[1]).toHaveAttribute("href", "/statements/bad/review");
    expect(rows[2]).toHaveAttribute("href", "/reconciliation/review-queue");

    expect(within(rows[1]).getByText("bad.pdf")).toBeInTheDocument();
    expect(within(rows[0]).getByText("0% confidence")).toBeInTheDocument();

    // AC22.11.2: each row explains *why* it was flagged, not just a score.
    expect(within(rows[0]).getByText(/no matching ledger entry/i)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/balance didn't reconcile/i)).toBeInTheDocument();
  });

  it("AC22.6.1 shows an all-clear empty state when nothing needs attention", async () => {
    mockSources({
      statements: [{ id: "x", original_filename: "ok.pdf", status: "approved", transactions: [] }],
      stats: { total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} },
      processing: [],
    });

    render(<AttentionPage />);

    await waitFor(() => expect(screen.getByText("All clear")).toBeInTheDocument());
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("AC22.6.1 surfaces a retryable error state when the sources fail to load", async () => {
    // Reject one source and resolve the rest so Promise.all rejects without
    // leaving sibling promises unhandled.
    mockedApiFetch.mockImplementation((path: string) =>
      path === "/api/statements" ? Promise.reject(new Error("offline")) : Promise.resolve(null),
    );

    render(<AttentionPage />);

    await waitFor(() => expect(screen.getByText("Couldn't load your attention items")).toBeInTheDocument());
    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
