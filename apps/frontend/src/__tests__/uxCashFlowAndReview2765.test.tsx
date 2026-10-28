// AC-reporting.report-integrity.3
// AC-extraction.fe-stage1-review.7
// AC-extraction.human-source-review.4
// AC-extraction.2477.1
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReportsPage from "@/app/(main)/reports/page";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { SourceEnvelopeConfirmation, type EnvelopeDraft } from "@/components/review/StatementReview";
import { apiOperation } from "@/lib/api-client";

import { setTestUrl } from "./helpers/nextNavigation";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock("next/navigation", async () => {
  const nav = (await import("./helpers/nextNavigation")).nextNavigationMock;
  return {
    ...nav,
    useParams: vi.fn(() => ({ id: "stmt-2765" })),
  };
});

vi.mock("@/hooks/useBaseCurrency", () => ({
  useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }),
}));

vi.mock("@/components/charts/SankeyChart", () => ({
  SankeyChart: () => <div>SankeyChartMock</div>,
}));

vi.mock("@/hooks/useCurrencies", () => ({
  useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }),
}));

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  API_URL: "http://localhost:8000",
  apiOperation: vi.fn(),
  apiOperationDownload: vi.fn(),
}));

describe("Issue #2765 CashFlow unclassified bridge and statement review UX", () => {
  const mockedApi = vi.mocked(apiOperation);

  beforeEach(() => {
    mockedApi.mockReset();
    setTestUrl("/reports?tab=cash-flow");
  });

  it("renders non-zero cash_bridge.unclassified_cash note in Cash reconciliation card", async () => {
    mockedApi.mockResolvedValue({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      currency: "SGD",
      operating: [],
      investing: [],
      financing: [],
      summary: {
        operating_activities: "0.00",
        investing_activities: "0.00",
        financing_activities: "0.00",
        net_cash_flow: "-1250.00",
        beginning_cash: "5000.00",
        ending_cash: "3750.00",
      },
      cash_bridge: {
        classified_activity: "0.00",
        unclassified_cash: "-1250.00",
        fx_effect: "0.00",
        cash_delta: "-1250.00",
        discrepancy: "0.00",
        reconciles: true,
      },
      proof_state: "unproven",
      proof_reasons: ["cash_event_classification_ambiguous"],
    });

    render(<ReportsPage />);

    const reconciliation = await screen.findByLabelText("Cash reconciliation");
    expect(reconciliation).toHaveTextContent(/Includes/i);
    expect(reconciliation).toHaveTextContent(/1,250\.00/);
    expect(reconciliation).toHaveTextContent(/in transfers in transit \/ unclassified cash movement/i);
  });

  it("shows balance verification loading status while statement review query is in flight", async () => {
    let resolveReview: (val: unknown) => void = () => undefined;
    const pendingReviewPromise = new Promise((resolve) => {
      resolveReview = resolve;
    });

    mockedApi.mockImplementation((operationId: string) => {
      if (operationId === "get_statement_statements__statement_id__get") {
        return Promise.resolve({
          id: "stmt-2765",
          original_filename: "dbs_jan.pdf",
          institution: "DBS",
          currency: "SGD",
          period_start: "2026-01-01",
          period_end: "2026-01-31",
          opening_balance: "1000.00",
          closing_balance: "1200.00",
          status: "parsed",
          transactions: [],
        });
      }
      if (operationId === "get_statement_for_review_statements__statement_id__review_get") {
        return pendingReviewPromise;
      }
      if (operationId === "list_pending_review_statements_pending_review_get") {
        return Promise.resolve({ items: [{ id: "stmt-2765" }], total: 1 });
      }
      if (operationId === "get_review_conflicts_review_conflicts__statement_id__get") {
        return Promise.resolve({ duplicates: [], transfer_pairs: [] });
      }
      return Promise.resolve({});
    });

    renderReviewComponent(<StatementDetailPage /> as never);

    expect(await screen.findByText("Loading balance verification...")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();

    resolveReview({
      id: "stmt-2765",
      account_id: "acc-1",
      currency: "SGD",
      period_start: "2026-01-01",
      period_end: "2026-01-31",
      opening_balance: "1000.00",
      closing_balance: "1200.00",
      balance_validation_result: {
        opening_balance: "1000.00",
        closing_balance: "1200.00",
        calculated_closing: "1200.00",
        opening_delta: "0.00",
        closing_delta: "0.00",
        opening_match: true,
        closing_match: true,
      },
      source_missing_facts: [],
      source_envelope_reviewable: false,
      reviewed_envelope: null,
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    expect(screen.queryByText("Loading balance verification...")).toBeNull();
  });

  it("fills standard rationale in 1 click inside SourceEnvelopeConfirmation", () => {
    const initialDraft: EnvelopeDraft = {
      accountId: "acc-1",
      currency: "SGD",
      periodStart: "2026-01-01",
      periodEnd: "2026-01-31",
      openingBalance: "1000.00",
      closingBalance: "1200.00",
      rationale: "",
    };
    let updatedDraft = initialDraft;

    render(
      <SourceEnvelopeConfirmation
        requiresEnvelopeConfirmation
        requiresOtherSourceReview={false}
        sourceMissingFacts={[]}
        missingFactLabels={{}}
        envelopeDraft={initialDraft}
        onDraftChange={(updater) => {
          updatedDraft = updater(updatedDraft);
        }}
        custodyAccounts={[{ id: "acc-1", name: "DBS Multiplier", currency: "SGD" }]}
        onConfirm={() => {}}
        isPending={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Use standard confirmation note" }));
    expect(updatedDraft.rationale).toBe(
      "Confirmed statement header and opening/closing balances against source file",
    );
  });
});
