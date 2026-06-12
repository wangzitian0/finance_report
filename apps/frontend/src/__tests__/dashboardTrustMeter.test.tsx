import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TrustMeter } from "@/components/home/TrustMeter";
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

function mockSources(stats: unknown, statements: unknown[] = [], processing: unknown[] = []) {
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/statements") return Promise.resolve({ items: statements, total: statements.length });
    if (path === "/api/reconciliation/stats") return Promise.resolve(stats);
    if (path === "/api/accounts/processing/pending") return Promise.resolve({ items: processing, total: processing.length });
    return Promise.resolve(null);
  });
}

describe("Home trust meter (EPIC-022 AC22.6.2)", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("AC22.6.2 renders trusted / needs-confirmation / low-confidence counts and links to the attention queue", async () => {
    mockSources(
      { total_transactions: 100, matched_transactions: 80, unmatched_transactions: 5, pending_review: 3, auto_accepted: 70, match_rate: 80, score_distribution: {} },
    );

    render(<TrustMeter />);

    await waitFor(() => expect(screen.getByText("Data trust")).toBeInTheDocument());
    expect(screen.getByText("Trusted").previousSibling).toHaveTextContent("80");
    // unmatched (1 item) + pending review (1 item) = 2 needing confirmation.
    expect(screen.getByText("Needs your confirmation").previousSibling).toHaveTextContent("2");
    // unmatched is below the low-confidence threshold.
    expect(screen.getByText("Low confidence").previousSibling).toHaveTextContent("1");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/attention");
  });

  it("AC22.6.2 stays silent when nothing needs attention", async () => {
    mockSources(
      { total_transactions: 10, matched_transactions: 10, unmatched_transactions: 0, pending_review: 0, auto_accepted: 10, match_rate: 100, score_distribution: {} },
    );

    const { container } = render(<TrustMeter />);

    // Give the effect a tick to resolve, then assert nothing rendered.
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("AC22.6.2 stays silent (no crash) when the sources fail to load", async () => {
    // Reject one source and resolve the rest so Promise.all rejects without
    // leaving sibling promises unhandled.
    mockedApiFetch.mockImplementation((path: string) =>
      path === "/api/statements" ? Promise.reject(new Error("offline")) : Promise.resolve(null),
    );

    const { container } = render(<TrustMeter />);

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
