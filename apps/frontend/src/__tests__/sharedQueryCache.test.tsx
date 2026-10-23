// #2583 S4 — one cache entry per request across routes.
//
// Upload, Attention, the Home trust meter and the reconciliation Workbench read the same
// statement list, reconciliation stats and processing queue. These tests mount two routes on
// one QueryClient and count the requests per operation.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NeedsConfirmationQueue } from "@/components/audit/NeedsConfirmationQueue";
import UploadPage from "@/app/(main)/upload/page";
import { HomeActionBanner } from "@/components/home/HomeActionBanner";
import { apiOperation } from "@/lib/api-client";
import { createAppQueryClient } from "@/lib/queryClient";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/statements/StatementUploader", () => ({
  default: ({ onUploadComplete }: { onUploadComplete: () => void }) => (
    <button onClick={onUploadComplete}>UploadMock</button>
  ),
}));
vi.mock("@/components/assets/GuidedEvidenceForm", () => ({ default: () => <div /> }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

const STATS = {
  total_transactions: 100,
  matched_transactions: 80,
  unmatched_transactions: 5,
  pending_review: 3,
  auto_accepted: 70,
  match_rate: 80,
  score_distribution: {},
};

function statement(id: string, status: string) {
  return { id, original_filename: `${id}.pdf`, institution: "DBS", status, transactions: [] };
}

function mockApi(statementPages: Array<{ items: unknown[]; total: number }>) {
  let statementReads = 0;
  mockedApiOperation.mockImplementation(((operationId: string) => {
    if (operationId === "list_statements_statements_get") {
      const page = statementPages[Math.min(statementReads, statementPages.length - 1)];
      statementReads += 1;
      return Promise.resolve(page);
    }
    if (operationId === "reconciliation_stats_reconciliation_stats_get") return Promise.resolve(STATS);
    if (operationId === "list_processing_pending_accounts_processing_pending_get") {
      return Promise.resolve({ items: [], total: 0 });
    }
    return Promise.reject(new Error(`Unexpected operation ${operationId}`));
  }) as never);
}

function callsTo(operationId: string): number {
  return mockedApiOperation.mock.calls.filter(([id]) => id === operationId).length;
}

function sharedClient() {
  return new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: false } } });
}

function renderOn(client: QueryClient, ui: ReactNode) {
  return render(<>{ui}</>, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

describe("shared query cache (#2583 S4)", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 the Home action banner and the attention queue mounted together request each source once", async () => {
    mockApi([{ items: [statement("s1", "parsed")], total: 1 }]);

    renderOn(
      sharedClient(),
      <>
        <HomeActionBanner />
        <NeedsConfirmationQueue />
      </>,
    );

    await screen.findByRole("region", { name: "Needs attention" });
    await within(screen.getByTestId("needs-confirmation-queue")).findByText("5 unmatched transactions");

    expect(callsTo("list_statements_statements_get")).toBe(1);
    expect(callsTo("reconciliation_stats_reconciliation_stats_get")).toBe(1);
    expect(callsTo("list_processing_pending_accounts_processing_pending_get")).toBe(1);
    expect(callsTo("list_unmatched_reconciliation_unmatched_get")).toBe(1);
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 the attention queue reads the list that the upload page loaded", async () => {
    mockApi([{ items: [statement("s1", "approved")], total: 1 }]);
    const client = sharedClient();

    const upload = renderOn(client, <UploadPage />);
    await waitFor(() => expect(screen.getByText("s1.pdf")).toBeInTheDocument());
    upload.unmount();
    expect(callsTo("list_statements_statements_get")).toBe(1);

    renderOn(client, <NeedsConfirmationQueue />);
    await screen.findByText("5 unmatched transactions");
    expect(callsTo("list_statements_statements_get")).toBe(1);
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 the upload page polls every three seconds while a statement parses and stops when none parses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi([
      { items: [statement("s1", "parsing")], total: 1 },
      { items: [statement("s1", "parsing")], total: 1 },
      { items: [statement("s1", "parsed")], total: 1 },
    ]);

    renderOn(sharedClient(), <UploadPage />);
    await screen.findByText("AI Parsing in Progress");
    expect(callsTo("list_statements_statements_get")).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(callsTo("list_statements_statements_get")).toBe(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(callsTo("list_statements_statements_get")).toBe(3);
    await waitFor(() => expect(screen.queryByText("AI Parsing in Progress")).toBeNull());

    // Nothing parses now: sixty seconds later the page has issued no further request.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(callsTo("list_statements_statements_get")).toBe(3);
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 the upload page does not poll when no statement parses on arrival", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi([{ items: [statement("s1", "approved")], total: 1 }]);

    renderOn(sharedClient(), <UploadPage />);
    await screen.findByText("s1.pdf");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(callsTo("list_statements_statements_get")).toBe(1);
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 the upload page renders an empty list, without polling, when the answer has no items", async () => {
    // Mocked and degraded backends answer `{}`. The interval function runs on every list update.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedApiOperation.mockResolvedValue({});

    renderOn(sharedClient(), <UploadPage />);
    await screen.findByText("No statements uploaded yet");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(callsTo("list_statements_statements_get")).toBe(1);
  });

  // AC-reporting.fe-fetch-budget.3
  it("AC-reporting.fe-fetch-budget.3 an upload completion refreshes the shared list that other routes read", async () => {
    mockApi([
      { items: [], total: 0 },
      { items: [statement("s2", "parsing")], total: 1 },
    ]);
    const client = createAppQueryClient();

    renderOn(client, <UploadPage />);
    await screen.findByText("No statements uploaded yet");

    fireEvent.click(screen.getAllByText("UploadMock")[0]);
    await screen.findByText("s2.pdf");
    expect(callsTo("list_statements_statements_get")).toBe(2);
    expect(client.getQueryData(["statements", "list"])).toEqual({
      items: [statement("s2", "parsing")],
      total: 1,
    });
  });
});
