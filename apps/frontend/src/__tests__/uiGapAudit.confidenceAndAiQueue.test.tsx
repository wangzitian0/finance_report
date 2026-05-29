import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AiSuggestionsPage from "@/app/(main)/review/ai-suggestions/page";
import AiSettingsPage from "@/app/(main)/settings/ai/page";
import AuditTrailPanel from "@/components/AuditTrailPanel";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("EPIC-018 / UI Gap Audit / Phase 5 Confidence + AI Review UI", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("AC18.5.1 — ConfidenceBadge renders confidence tier labels", () => {
    const tiers = ["TRUSTED", "HIGH", "MEDIUM", "LOW"] as const;

    render(
      <div>
        {tiers.map((tier) => (
          <ConfidenceBadge key={tier} tier={tier} />
        ))}
      </div>,
    );

    for (const tier of tiers) {
      const badge = screen.getByText(tier);
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute(
        "title",
        expect.stringContaining("Manual entries are TRUSTED; AI-extracted are LOW"),
      );
    }
  });

  it("AC18.5.2 — Journal page surfaces ConfidenceBadge tier", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        {
          id: "entry-1",
          entry_date: "2026-04-01",
          memo: "Processing account transfer",
          source_type: "system",
          confidence_tier: "LOW",
          status: "posted",
          lines: [{ id: "line-1", account_id: "account-1", direction: "DEBIT", amount: 10, currency: "SGD" }],
          created_at: "2026-04-01T00:00:00Z",
        },
      ],
      total: 1,
    });

    const { default: JournalPage } = await import("@/app/(main)/journal/page");
    render(<JournalPage />);

    await waitFor(() => expect(screen.getByText("Processing account transfer")).toBeInTheDocument());
    expect(screen.getByText("LOW")).toBeInTheDocument();
  });

  it("AC18.5.3 — AI Suggestion Review Queue page renders suggestions", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        {
          suggestion_id: "00000000-0000-0000-0000-000000000011",
          transaction: "CARD PURCHASE COFFEE",
          suggested_category_or_match: "Expense - Food & Dining",
          ai_score: 72,
          ai_reasoning: "Merchant name indicates dining.",
        },
      ],
      total: 1,
    });

    render(<AiSuggestionsPage />);

    expect(await screen.findByText("CARD PURCHASE COFFEE")).toBeInTheDocument();
    expect(screen.getByText("Expense - Food & Dining")).toBeInTheDocument();
    expect(screen.getByText("Merchant name indicates dining.")).toBeInTheDocument();
  });

  it("AC18.5.4 — feedback POST on accept/reject/edit", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [
          {
            suggestion_id: "00000000-0000-0000-0000-000000000012",
            transaction: "PAYNOW TRANSFER",
            suggested_category_or_match: "Transfer match",
            ai_score: 81,
            ai_reasoning: "Descriptions are semantically similar.",
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce({ id: "feedback-1" })
      .mockResolvedValueOnce({ id: "feedback-2" })
      .mockResolvedValueOnce({ id: "feedback-3" });

    render(<AiSuggestionsPage />);

    await screen.findByText("PAYNOW TRANSFER");
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "Expense - Transport" } });
    fireEvent.click(screen.getByRole("button", { name: "Edit-then-Accept" }));

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/ai/feedback", {
        method: "POST",
        body: JSON.stringify({
          suggestion_id: "00000000-0000-0000-0000-000000000012",
          action: "edit_accept",
          corrected_value: { value: "Expense - Transport" },
        }),
      }),
    );
  });

  it("test_AC8_13_48 — AI suggestions page renders load errors", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("suggestions unavailable"));

    render(<AiSuggestionsPage />);

    expect(await screen.findByText("suggestions unavailable")).toBeInTheDocument();
  });

  it("AC18.5.5 — Settings AI toggles persist", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ enable_ai_reconciliation: true, enable_ai_classification: false })
      .mockResolvedValueOnce({ enable_ai_reconciliation: true, enable_ai_classification: true });

    render(<AiSettingsPage />);

    const reconciliationToggle = await screen.findByLabelText("Enable AI reconciliation");
    const classificationToggle = screen.getByLabelText("Enable AI classification");
    expect(reconciliationToggle).toBeChecked();
    expect(classificationToggle).not.toBeChecked();

    fireEvent.click(classificationToggle);

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/users/me/settings", {
        method: "PATCH",
        body: JSON.stringify({ enable_ai_classification: true }),
      }),
    );
  });

  it("AC18.5.6 — Audit Trail panel renders provenance", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-04-01T10:00:00Z",
          actor: "ai",
          action: "classified",
          old_value: { category: null },
          new_value: { category: "Food & Dining" },
        },
      ],
    });

    render(<AuditTrailPanel transactionId="00000000-0000-0000-0000-000000000013" />);

    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
    expect(screen.getByText("ai")).toBeInTheDocument();
    expect(screen.getByText("classified")).toBeInTheDocument();
    expect(screen.getByText(/Food & Dining/)).toBeInTheDocument();
  });

  it("AC18.5.7 — AI settings mount reflects saved toggles", async () => {
    mockedApiFetch.mockResolvedValueOnce({ enable_ai_reconciliation: false, enable_ai_classification: true });

    render(<AiSettingsPage />);

    expect(await screen.findByLabelText("Enable AI reconciliation")).not.toBeChecked();
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked();
  });

  it("test_AC8_13_48 — AI settings handles load and reconciliation update failures", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("settings unavailable"));

    render(<AiSettingsPage />);

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/users/me/settings"));
    expect(screen.getByText("Loading AI settings...")).toBeInTheDocument();

    mockedApiFetch.mockReset();
    mockedApiFetch
      .mockResolvedValueOnce({ enable_ai_reconciliation: false, enable_ai_classification: true })
      .mockRejectedValueOnce(new Error("update failed"));

    render(<AiSettingsPage />);

    const reconciliationToggle = await screen.findByLabelText("Enable AI reconciliation");
    fireEvent.click(reconciliationToggle);

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/api/users/me/settings", {
        method: "PATCH",
        body: JSON.stringify({ enable_ai_reconciliation: true }),
      }),
    );
    expect(await screen.findByText("update failed")).toBeInTheDocument();
  });
});
