import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditPage from "@/app/(main)/audit/page";
import { ActionChecklist } from "@/components/audit/ActionChecklist";
import { InvariantChecksGrid } from "@/components/audit/InvariantChecksGrid";
import { TemporalTimelineGrid } from "@/components/audit/TemporalTimelineGrid";
import { TrustScoreHero } from "@/components/audit/TrustScoreHero";
import { TrustMeter } from "@/components/home/TrustMeter";
import {
  getGradeColor,
  getGradeLabel,
  useDataQualityHealth,
} from "@/hooks/useDataQualityHealth";
import { apiOperation } from "@/lib/api-client";
import type {
  PersonalDataQualityHealthResponse,
  QualityActionItem,
  QualityGrade,
} from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

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
        screen.getByText("Temporal Continuity & Rollforward"),
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

    it("renders 100% audit-ready message when action items list is empty", () => {
      render(<ActionChecklist actionItems={[]} />);

      expect(
        screen.getByText("100% Invariant Perfection · Audit Ready"),
      ).toBeInTheDocument();
    });
  });

  describe("AuditPage", () => {
    it("loads and displays full observatory with deep links", async () => {
      mockedApiOperation.mockResolvedValueOnce(mockHealthData as any);

      render(<AuditPage />, { wrapper: createWrapper() });

      expect(
        screen.getByText("Financial Data Quality & Audit Observatory"),
      ).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByText("Grade A · Audit-Ready")).toBeInTheDocument();
      });

      // Underlying ledgers deep links
      expect(screen.getByText("Accounting Machinery & Ledgers")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Trust/ })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Reconciliation/ })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Journal/ })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Processing/ })).toBeInTheDocument();
    });
  });

  describe("TrustMeter on HomePage", () => {
    it("renders Audit-Ready link to /audit when 0 items need confirmation", async () => {
      mockedApiOperation
        .mockResolvedValueOnce({ items: [], total: 0 } as any) // list_statements
        .mockResolvedValueOnce({
          total_transactions: 10,
          matched_transactions: 10,
          unmatched_transactions: 0,
          pending_review: 0,
          auto_accepted: 0,
          match_rate: 1.0,
        } as any) // reconciliation_stats
        .mockResolvedValueOnce({ items: [], total: 0 } as any); // processing_pending

      render(<TrustMeter />);

      await waitFor(() => {
        expect(screen.getByText("Financial Data Quality")).toBeInTheDocument();
      });
      expect(screen.getByText("Audit Ready · 100%")).toBeInTheDocument();
      expect(screen.getByRole("link")).toHaveAttribute("href", "/audit");
    });
  });
});
