import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AiSuggestionsPage from "@/app/(main)/review/ai-suggestions/page";
import AiSettingsPage from "@/components/settings/AiSettingsPanel";
import AuditTrailPanel from "@/components/AuditTrailPanel";
import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

const mockedApiOperation = vi.mocked(apiOperation);

describe("EPIC-018 / UI Gap Audit / Phase 5 Confidence + AI Review UI", () => {
  beforeEach(() => {
    mockedApiOperation.mockReset();
  });

  // AC-meta.fe-app-shell2.1
  it("AC18.5.1 — ConfidenceBadge renders confidence tier labels", () => {
    const tiers = [
      "DETERMINISTIC",
      "TRUSTED",
      "HIGH",
      "MEDIUM",
      "LOW",
    ] as const;

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
        expect.stringContaining(
          "Deterministic system facts and manual entries are trusted",
        ),
      );
    }
  });

  // AC-ledger.fe-accounts2.4
  it("AC18.5.2 — Journal page surfaces ConfidenceBadge tier", async () => {
    mockedApiOperation.mockResolvedValueOnce({
      items: [
        {
          id: "entry-1",
          entry_date: "2026-04-01",
          memo: "Processing account transfer",
          source_type: "system",
          confidence_tier: "LOW",
          status: "posted",
          lines: [
            {
              id: "line-1",
              account_id: "account-1",
              direction: "DEBIT",
              amount: 10,
              currency: "SGD",
            },
          ],
          created_at: "2026-04-01T00:00:00Z",
        },
      ],
      total: 1,
    } as any);

    const { default: JournalPage } = await import("@/app/(main)/journal/page");
    render(<JournalPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Processing account transfer"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("LOW")).toBeInTheDocument();
  });

  // AC-reconciliation.fe-remainder-reconciliation.2
  it("AC18.5.3 — AI Suggestion Review Queue page renders suggestions", async () => {
    mockedApiOperation.mockResolvedValueOnce({
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
    } as any);

    render(<AiSuggestionsPage />);

    expect(
      (await screen.findAllByText("CARD PURCHASE COFFEE")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Expense - Food & Dining").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Merchant name indicates dining.").length,
    ).toBeGreaterThan(0);
  });

  // AC-reconciliation.fe-remainder-reconciliation.3
  it("AC18.5.4 — feedback POST on accept/reject/edit", async () => {
    mockedApiOperation
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
      } as any)
      .mockResolvedValueOnce({ id: "feedback-1" } as any)
      .mockResolvedValueOnce({ id: "feedback-2" } as any)
      .mockResolvedValueOnce({ id: "feedback-3" } as any);

    render(<AiSuggestionsPage />);

    await screen.findAllByText("PAYNOW TRANSFER");
    const mobileCard = screen.getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000012",
    );
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Accept" }));
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));
    fireEvent.change(within(mobileCard).getByLabelText("Corrected value"), {
      target: { value: "Expense - Transport" },
    });
    fireEvent.click(
      within(mobileCard).getByRole("button", { name: "Edit-then-Accept" }),
    );

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith(
        "create_ai_feedback_ai_feedback_post",
        {
          body: {
            suggestion_id: "00000000-0000-0000-0000-000000000012",
            action: "edit_accept",
            corrected_value: { value: "Expense - Transport" },
          },
        },
      ),
    );
  });

  it("AC16.25.2 — AI suggestions mobile cards expose feedback actions", async () => {
    mockedApiOperation
      .mockResolvedValueOnce({
        items: [
          {
            suggestion_id: "00000000-0000-0000-0000-000000000025",
            transaction: "MOBILE CARD PURCHASE",
            suggested_category_or_match: "Expense - Food & Dining",
            ai_score: 72,
            ai_reasoning:
              "Merchant category and prior corrections match dining.",
          },
        ],
        total: 1,
      } as any)
      .mockResolvedValueOnce({ id: "feedback-accept" } as any)
      .mockResolvedValueOnce({ id: "feedback-reject" } as any)
      .mockResolvedValueOnce({ id: "feedback-edit" } as any);

    render(<AiSuggestionsPage />);

    const mobileList = await screen.findByTestId("ai-suggestions-mobile-list");
    const mobileCard = within(mobileList).getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000025",
    );

    expect(
      within(mobileCard).getByText("MOBILE CARD PURCHASE"),
    ).toBeInTheDocument();
    expect(
      within(mobileCard).getByLabelText("Corrected value"),
    ).toBeInTheDocument();
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Accept" }));
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));
    fireEvent.change(within(mobileCard).getByLabelText("Corrected value"), {
      target: { value: "Expense - Transport" },
    });
    fireEvent.click(
      within(mobileCard).getByRole("button", { name: "Edit-then-Accept" }),
    );

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith(
        "create_ai_feedback_ai_feedback_post",
        {
          body: {
            suggestion_id: "00000000-0000-0000-0000-000000000025",
            action: "edit_accept",
            corrected_value: { value: "Expense - Transport" },
          },
        },
      ),
    );
  });

  it("test_AC8_13_48 — AI suggestions page renders load errors", async () => {
    mockedApiOperation.mockRejectedValueOnce(new Error("suggestions unavailable"));

    render(<AiSuggestionsPage />);

    expect(
      await screen.findByText("suggestions unavailable"),
    ).toBeInTheDocument();
  });

  // AC-llm.fe-ai-settings2.1
  it("AC18.5.5 — Settings AI toggles persist", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: true,
          enable_ai_classification: false,
        } as any;
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        return {
          enable_ai_reconciliation: true,
          enable_ai_classification: true,
        } as any;
      }
      return {} as any;
    });

    render(<AiSettingsPage />);

    const reconciliationToggle = await screen.findByLabelText(
      "Enable AI reconciliation",
    );
    const classificationToggle = screen.getByLabelText(
      "Enable AI classification",
    );
    expect(reconciliationToggle).toBeChecked();
    expect(classificationToggle).not.toBeChecked();

    fireEvent.click(classificationToggle);
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("patch_current_user_settings_users_me_settings_patch", {
        body: {
          enable_ai_reconciliation: true,
          enable_ai_classification: true,
        },
      }),
    );
  });

  // AC-extraction.fe-remainder-extraction.1
  it("AC18.5.6 — Audit Trail panel renders provenance", async () => {
    mockedApiOperation.mockResolvedValueOnce({
      items: [
        {
          timestamp: "2026-04-01T10:00:00Z",
          actor: "ai",
          action: "classified",
          old_value: { category: null },
          new_value: { category: "Food & Dining" },
        },
      ],
    } as any);

    render(
      <AuditTrailPanel transactionId="00000000-0000-0000-0000-000000000013" />,
    );

    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
    expect(await screen.findByText("ai")).toBeInTheDocument();
    expect(screen.getByText("classified")).toBeInTheDocument();
    expect(screen.getByText(/Food & Dining/)).toBeInTheDocument();
  });

  // AC-llm.fe-ai-settings2.2
  it("AC18.5.7 — AI settings mount reflects saved toggles", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: false,
          enable_ai_classification: true,
        } as any;
      }
      return {} as any;
    });

    render(<AiSettingsPage />);

    expect(
      await screen.findByLabelText("Enable AI reconciliation"),
    ).not.toBeChecked();
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked();
  });

  it("test_AC8_13_48 — AI settings handles load and reconciliation update failures", async () => {
    mockedApiOperation.mockRejectedValueOnce(
      new Error("settings unavailable"),
    );

    render(<AiSettingsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "settings unavailable",
    );

    mockedApiOperation.mockReset();
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: false,
          enable_ai_classification: true,
        } as any;
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        throw new Error("update failed");
      }
      return {} as any;
    });

    render(<AiSettingsPage />);

    const reconciliationToggle = await screen.findByLabelText(
      "Enable AI reconciliation",
    );
    fireEvent.click(reconciliationToggle);
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("patch_current_user_settings_users_me_settings_patch", {
        body: {
          enable_ai_reconciliation: true,
          enable_ai_classification: true,
        },
      }),
    );
    expect(await screen.findByText("update failed")).toBeInTheDocument();
  });
});
