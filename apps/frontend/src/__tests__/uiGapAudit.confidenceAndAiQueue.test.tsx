import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiSuggestionsQueue } from "@/components/audit/AiSuggestionsQueue";
import AiSettingsPage from "@/components/settings/AiSettingsPanel";
import { AuditTrailPanel } from "@/components/journal/JournalEntryDetailsModal";
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

    render(<AiSuggestionsQueue />);

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
      .mockResolvedValueOnce({ id: "feedback-1", effect: "accepted" } as any)
      .mockResolvedValueOnce({ id: "feedback-2", effect: "rejected" } as any)
      .mockResolvedValueOnce({ id: "feedback-3", effect: "corrected" } as any);

    render(<AiSuggestionsQueue />);

    await screen.findAllByText("PAYNOW TRANSFER");
    const mobileCard = screen.getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000012",
    );
    // One decision at a time: the buttons are locked while a request is in flight.
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Accept" }));
    await within(mobileCard).findByText(/^Accepted\./);
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));
    await within(mobileCard).findByText(/^Rejected\./);
    fireEvent.change(within(mobileCard).getByLabelText("Corrected value"), {
      target: { value: "TRANSPORT" },
    });
    fireEvent.click(
      within(mobileCard).getByRole("button", { name: "Edit-then-Accept" }),
    );
    await within(mobileCard).findByText(/^Corrected\./);

    expect(mockedApiOperation).toHaveBeenCalledWith(
      "create_ai_feedback_ai_feedback_post",
      {
        body: {
          suggestion_id: "00000000-0000-0000-0000-000000000012",
          action: "edit_accept",
          corrected_value: { value: "TRANSPORT" },
        },
      },
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
            direction: "OUT",
            ai_score: 72,
            ai_reasoning:
              "Merchant category and prior corrections match dining.",
          },
        ],
        total: 1,
      } as any)
      .mockResolvedValueOnce({ id: "feedback-edit", effect: "corrected" } as any);

    render(<AiSuggestionsQueue />);

    const mobileList = await screen.findByTestId("ai-suggestions-mobile-list");
    const mobileCard = within(mobileList).getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000025",
    );

    expect(
      within(mobileCard).getByText("MOBILE CARD PURCHASE"),
    ).toBeInTheDocument();
    const select = within(mobileCard).getByLabelText("Corrected value") as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain("DINING");
    expect(optionValues).toContain("TRANSFER");
    expect(optionValues).not.toContain("SALARY");
    expect(
      within(mobileCard).getByRole("button", { name: "Accept" }),
    ).toBeEnabled();
    expect(
      within(mobileCard).getByRole("button", { name: "Reject" }),
    ).toBeEnabled();
    fireEvent.change(select, {
      target: { value: "TRANSPORT" },
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
            corrected_value: { value: "TRANSPORT" },
          },
        },
      ),
    );
  });

  // AC-extraction.classification-hardening.6
  it("AC-extraction.classification-hardening.6 — shows the effect that the server reports and the server refusal", async () => {
    const suggestion = {
      suggestion_id: "00000000-0000-0000-0000-000000000031",
      transaction: "CARD PURCHASE COFFEE",
      suggested_category_or_match: "DINING",
      ai_score: 72,
      ai_reasoning: "Merchant name indicates dining.",
    };
    mockedApiOperation
      .mockResolvedValueOnce({ items: [suggestion], total: 1 } as any)
      .mockResolvedValueOnce({ id: "feedback-1", effect: "rejected" } as any)
      .mockResolvedValueOnce({ id: "feedback-2", effect: "recorded" } as any)
      .mockRejectedValueOnce(
        new Error("The corrected value is not a category. Use one of: SALARY"),
      );

    render(<AiSuggestionsQueue />);

    await screen.findAllByText("CARD PURCHASE COFFEE");
    const mobileCard = screen.getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000031",
    );
    // The live region exists before any decision, so a screen reader announces the first one.
    expect(within(mobileCard).getByRole("status")).toBeEmptyDOMElement();

    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));
    expect(await within(mobileCard).findByRole("status")).toHaveTextContent(
      "Rejected. The approval uses the default category.",
    );

    // The server answers "recorded" when the draft is gone. The label must not claim an effect.
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(within(mobileCard).getByRole("status")).toHaveTextContent(
        "Feedback saved. It did not change the suggestion.",
      ),
    );

    fireEvent.change(within(mobileCard).getByLabelText("Corrected value"), {
      target: { value: "SALARY" },
    });
    fireEvent.click(
      within(mobileCard).getByRole("button", { name: "Edit-then-Accept" }),
    );

    expect(await within(mobileCard).findByRole("alert")).toHaveTextContent(
      "The corrected value is not a category. Use one of: SALARY",
    );
  });

  it("AC-extraction.classification-hardening.6 — locks the buttons of a row while its request is in flight", async () => {
    const suggestion = {
      suggestion_id: "00000000-0000-0000-0000-000000000032",
      transaction: "SLOW REQUEST",
      suggested_category_or_match: "DINING",
      ai_score: 72,
      ai_reasoning: "Merchant name indicates dining.",
    };
    let finish: (value: unknown) => void = () => {};
    mockedApiOperation
      .mockResolvedValueOnce({ items: [suggestion], total: 1 } as any)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }) as any,
      );

    render(<AiSuggestionsQueue />);

    await screen.findAllByText("SLOW REQUEST");
    const mobileCard = screen.getByTestId(
      "ai-suggestion-mobile-card-00000000-0000-0000-0000-000000000032",
    );
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));

    expect(
      await within(mobileCard).findByText("Saving..."),
    ).toBeInTheDocument();
    for (const name of ["Accept", "Reject", "Edit-then-Accept"]) {
      expect(within(mobileCard).getByRole("button", { name })).toBeDisabled();
    }
    fireEvent.click(within(mobileCard).getByRole("button", { name: "Reject" }));
    expect(mockedApiOperation).toHaveBeenCalledTimes(2);

    finish({ id: "feedback-1", effect: "rejected" });
    await within(mobileCard).findByText(/^Rejected\./);
    expect(
      within(mobileCard).getByRole("button", { name: "Accept" }),
    ).toBeEnabled();
  });

  it("test_AC8_13_48 — AI suggestions page renders load errors", async () => {
    mockedApiOperation.mockRejectedValueOnce(new Error("suggestions unavailable"));

    render(<AiSuggestionsQueue />);

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
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: false,
        } as any;
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        return {
          enable_ai_reconciliation: true,
          enable_ai_classification: true,
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: true,
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
        body: { enable_ai_classification: true },
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
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: true,
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
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: true,
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
        body: { enable_ai_reconciliation: true },
      }),
    );
    expect(await screen.findByText("update failed")).toBeInTheDocument();
  });
});
