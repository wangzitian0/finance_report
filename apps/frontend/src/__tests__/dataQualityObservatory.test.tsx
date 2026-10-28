import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditPage from "@/app/(main)/audit/page";
import {
  ActionChecklist,
  InvariantChecksGrid,
  TemporalTimelineGrid,
  TrustScoreHero,
} from "@/components/audit/AuditPanels";
import {
  getGradeColor,
  getGradeLabel,
  useDataQualityHealth,
} from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api-client";
import { setTestUrl } from "./helpers/nextNavigation";
import type {
  PersonalDataQualityHealthResponse,
  QualityActionItem,
  QualityGrade,
} from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);

const mockedApiOperation = vi.mocked(apiOperation);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

const mockHealthData: PersonalDataQualityHealthResponse = {
  score: 96,
  grade: "A_AUDIT_READY",
  as_of_date: "2026-10-09",
  currency: "SGD",
  equation_invariant: {
    is_healthy: true,
    name: "Accounting Equation Balance",
    summary: "Balance Sheet is strictly balanced (Assets = Liabilities + Equity)",
    detail: "No action required.",
    delta: "0.00",
  },
  temporal_continuity_invariant: {
    is_healthy: true,
    name: "Temporal Continuity & Rollforward",
    summary: "Continuous multi-period cash rollforward verified",
    detail: "Zero gaps detected across 12 rolling months.",
    delta: "0",
  },
  reconciliation_purity_invariant: {
    is_healthy: true,
    name: "Reconciliation & Debt Clearance Purity",
    summary: "Reconciliation purity verified with zero pending clearance items",
    detail: "Credit card settlements clear liability accounts with 0 P&L leakage.",
    delta: "0",
  },
  lineage_anchors_invariant: {
    is_healthy: true,
    name: "Evidence Lineage & Traceability Anchors",
    summary: "Full source-document-to-report lineage verified",
    detail: "Every report line traces directly to verified statement extraction evidence.",
    delta: "0",
  },
  timeline: [
    {
      month: "2026-01",
      statement_count: 1,
      has_gap: false,
      opening_balance: "1000.00",
      closing_balance: "1500.00",
      net_movement: "500.00",
      status: "HEALTHY",
    },
    {
      month: "2026-02",
      statement_count: 0,
      has_gap: true,
      opening_balance: null,
      closing_balance: null,
      net_movement: null,
      status: "GAP_DETECTED",
    },
    {
      month: "2026-03",
      statement_count: 1,
      has_gap: false,
      opening_balance: "1500.00",
      closing_balance: "1600.00",
      net_movement: "100.00",
      status: "PENDING_PROCESSING",
    },
  ],
  action_items: [
    {
      id: "upload_statement_2026-02",
      priority: "P1",
      title: "Upload Statement for 2026-02",
      description: "Missing statement for 2026-02 breaks temporal cash rollforward continuity.",
      score_boost: 10,
      action_type: "UPLOAD_STATEMENT",
      action_url: "/upload?month=2026-02",
    },
  ],
};

describe("Personal Data Quality Observatory (#2294)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Helper formatters", () => {
    it("returns correct color and labels for all grades", () => {
      expect(getGradeLabel("A_AUDIT_READY")).toBe("Grade A · Audit-Ready");
      expect(getGradeLabel("B_BALANCED_GAPS")).toBe("Grade B · Balanced with Gaps");
      expect(getGradeLabel("C_ATTENTION_NEEDED")).toBe("Grade C · Attention Needed");
      expect(getGradeLabel("D_OUT_OF_BALANCE")).toBe("Grade D · Out of Balance");

      expect(getGradeColor("A_AUDIT_READY")).toBe("var(--success)");
      expect(getGradeColor("B_BALANCED_GAPS")).toBe("var(--accent)");
      expect(getGradeColor("C_ATTENTION_NEEDED")).toBe("var(--warning)");
      expect(getGradeColor("D_OUT_OF_BALANCE")).toBe("var(--error)");
    });
  });

  describe("TrustScoreHero", () => {
    it("renders score, grade, metadata and trigger refresh", () => {
      const onRefresh = vi.fn();
      render(
        <TrustScoreHero
          score={96}
          grade="A_AUDIT_READY"
          asOfDate="2026-10-09"
          currency="SGD"
          onRefresh={onRefresh}
        />,
      );

      expect(screen.getByText("96")).toBeInTheDocument();
      expect(screen.getByText("Grade A · Audit-Ready")).toBeInTheDocument();
      expect(screen.getByText("2026-10-09")).toBeInTheDocument();
      expect(screen.getByText("SGD")).toBeInTheDocument();
      expect(screen.getByText("Re-evaluate")).toBeInTheDocument();
    });

    it("shows a grade that the frontend contract does not know as Unclassified in the muted color", () => {
      // A newer backend can send a grade before the generated frontend types know it.
      render(
        <TrustScoreHero
          score={50}
          grade={"E_NOT_IN_CONTRACT" as QualityGrade}
          asOfDate="2026-10-09"
          currency="SGD"
        />,
      );

      const badge = screen.getByText("Unclassified");
      expect(badge.style.color).toBe("var(--muted)");
    });
  });

  describe("InvariantChecksGrid", () => {
    it("renders all 4 core invariant cards and proofs", () => {
      render(
        <InvariantChecksGrid
          equationInvariant={mockHealthData.equation_invariant}
          temporalInvariant={mockHealthData.temporal_continuity_invariant}
          reconciliationInvariant={mockHealthData.reconciliation_purity_invariant}
          lineageInvariant={mockHealthData.lineage_anchors_invariant}
        />,
      );

      expect(
        screen.getByText("Accounting Equation Balance"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Temporal Continuity & continuity"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Reconciliation & Debt Clearance Purity"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Evidence Lineage & Traceability Anchors"),
      ).toBeInTheDocument();

      expect(
        screen.getByText("Assets = Liabilities + Equity (Δ = 0.00)"),
      ).toBeInTheDocument();
    });
  });

  describe("TemporalTimelineGrid", () => {
    it("renders monthly buckets and shows gap status", () => {
      render(<TemporalTimelineGrid timeline={mockHealthData.timeline} />);

      expect(screen.getByText("2026-01")).toBeInTheDocument();
      expect(screen.getByText("2026-02")).toBeInTheDocument();
      expect(screen.getByText("Missing Period")).toBeInTheDocument();
      expect(screen.getByText("Upload")).toBeInTheDocument();
      expect(screen.getByText("2026-03")).toBeInTheDocument();
      expect(screen.getByText("Review")).toBeInTheDocument();
    });
  });

  describe("ActionChecklist", () => {
    it("renders prioritized action cards when actions exist", () => {
      render(<ActionChecklist actionItems={mockHealthData.action_items} />);

      expect(screen.getByText("Upload Statement for 2026-02")).toBeInTheDocument();
      expect(screen.getByText("+10% Trust")).toBeInTheDocument();
      expect(screen.getByText("P1")).toBeInTheDocument();
      expect(screen.getByText("Resolve")).toBeInTheDocument();
    });

    // AC-reporting.net-worth-scope.21
    it("#2645 renders an action without a score boost when the boost is zero", () => {
      render(
        <ActionChecklist
          actionItems={[
            {
              id: "resolve_valuation_fx_rate",
              priority: "P1",
              title: "A Restricted Holding Has No FX Rate",
              description: "The full net worth cannot convert a restricted or illiquid valuation.",
              score_boost: 0,
              action_type: "RESOLVE_FX_RATE",
              action_url: "/portfolio?panel=evidence",
            },
          ]}
        />,
      );

      expect(screen.getByText("A Restricted Holding Has No FX Rate")).toBeInTheDocument();
      expect(screen.queryByText(/% Trust/)).toBeNull();
      expect(screen.getByRole("link", { name: /Resolve/ })).toHaveAttribute("href", "/portfolio?panel=evidence");
    });

    it("renders 100% audit-ready message when action items list is empty", () => {
      render(<ActionChecklist actionItems={[]} />);

      expect(
        screen.getByText("All Book Checks Pass · Audit Ready"),
      ).toBeInTheDocument();
    });
  });

  describe("AuditPage", () => {
    beforeEach(() => setTestUrl("/audit"));

    it("loads and displays full observatory with deep links and the needs-confirmation queue", async () => {
      mockedApiOperation.mockImplementation(async (op: string) => {
        if (op === "list_statements_statements_get") {
          return {
            items: [
              {
                id: "stmt-1",
                institution: "DBS",
                original_filename: "DBS_2026_01.pdf",
                status: "parsed",
                confidence_score: 65,
                balance_validated: false,
                period_start: "2026-01-01",
                period_end: "2026-01-31",
                transactions: [],
              },
            ],
          } as any;
        }
        if (op === "reconciliation_stats_reconciliation_stats_get") {
          return {
            total_transactions: 10,
            matched_transactions: 8,
            unmatched_transactions: 2,
            pending_review: 1,
            auto_accepted: 7,
            match_rate: 80,
          } as any;
        }
        if (op === "list_processing_pending_accounts_processing_pending_get") {
          return { items: [] } as any;
        }
        if (op === "list_ai_suggestions_ai_suggestions_get") return { items: [] } as any;
        return mockHealthData as any;
      });

      render(<AuditPage />, { wrapper: createWrapper() });

      expect(
        screen.getByRole("heading", { name: "Audit" }),
      ).toBeInTheDocument();

      // Items need the user: the page opens on the Needs you tab (#2646).
      await waitFor(() => {
        expect(screen.getByText("DBS_2026_01.pdf")).toBeInTheDocument();
      });

      act(() => setTestUrl("/audit?tab=health"));
      // Two unmatched rows hold the audit-ready grade (#2646).
      await waitFor(() => {
        expect(screen.getByText("Open items remain")).toBeInTheDocument();
      });
      expect(screen.queryByText(/Audit-Ready/)).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /Re-evaluate/i }));

      // Underlying ledgers deep links
      act(() => setTestUrl("/audit?tab=books"));
      expect(screen.queryByRole("link", { name: /Trust/ })).not.toBeInTheDocument();
      expect(screen.getAllByRole("link", { name: /Reconciliation/ }).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole("link", { name: /Journal/ })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Statements/ })).toHaveAttribute("href", "/upload");
    });

    it("keeps the attention rows of the sources that load when the statement and processing reads fail", async () => {
      mockedApiOperation.mockImplementation(async (op: string) => {
        if (op === "list_statements_statements_get") throw new Error("statements unavailable");
        if (op === "list_processing_pending_accounts_processing_pending_get") {
          throw new Error("processing unavailable");
        }
        if (op === "reconciliation_stats_reconciliation_stats_get") {
          return {
            total_transactions: 10,
            matched_transactions: 7,
            unmatched_transactions: 3,
            pending_review: 0,
            auto_accepted: 7,
            match_rate: 70,
          } as any;
        }
        if (op === "list_ai_suggestions_ai_suggestions_get") return { items: [] } as any;
        return mockHealthData as any;
      });

      render(<AuditPage />, { wrapper: createWrapper() });

      const bar = await screen.findByTestId("needs-confirmation-queue");
      const row = await within(bar).findByRole("link", { name: /3 unmatched transactions/ });
      expect(row).toHaveAttribute("href", "/reconciliation?tab=unmatched&from=attention");
      expect(within(row).getByText("0% confidence")).toBeInTheDocument();
    });

    it("keeps the statement attention rows when the reconciliation stats read fails", async () => {
      mockedApiOperation.mockImplementation(async (op: string) => {
        if (op === "reconciliation_stats_reconciliation_stats_get") throw new Error("stats unavailable");
        if (op === "list_processing_pending_accounts_processing_pending_get") return { items: [] } as any;
        if (op === "list_statements_statements_get") {
          return {
            items: [
              {
                id: "stmt-2",
                original_filename: "OCBC_2026_02.pdf",
                status: "parsed",
                confidence_score: 65,
                balance_validated: false,
              },
            ],
          } as any;
        }
        if (op === "list_ai_suggestions_ai_suggestions_get") return { items: [] } as any;
        return mockHealthData as any;
      });

      render(<AuditPage />, { wrapper: createWrapper() });

      const bar = await screen.findByTestId("needs-confirmation-queue");
      const row = await within(bar).findByRole("link", { name: /OCBC_2026_02\.pdf/ });
      expect(row).toHaveAttribute("href", "/statements/stmt-2?from=attention");
      expect(within(row).getByText("Balance needs review")).toBeInTheDocument();
      expect(within(row).getByText("40% confidence")).toBeInTheDocument();
    });

    it("renders error state with retry button when query fails", async () => {
      let healthReads = 0;
      mockedApiOperation.mockImplementation(async (op: string) => {
        if (op === "get_data_quality_health_reports_data_quality_get") {
          healthReads += 1;
          if (healthReads === 1) throw new Error("Network failure");
          return mockHealthData as any;
        }
        return { items: [] } as any;
      });

      render(<AuditPage />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(
          screen.getByText("Failed to evaluate data quality health."),
        ).toBeInTheDocument();
      });

      const retryBtn = screen.getByRole("button", { name: "Retry Evaluation" });
      expect(retryBtn).toBeInTheDocument();
      fireEvent.click(retryBtn);
    });
  });
});
