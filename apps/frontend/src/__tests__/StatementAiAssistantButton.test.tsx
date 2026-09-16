import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  StatementAiAssistantButton,
  buildStatementChatPrompt,
  buildTransactionChatPrompt,
} from "@/components/statements/StatementAiAssistantButton";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

describe("StatementAiAssistantButton & Prompt Helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Prompt Helpers", () => {
    it("builds correct prompt for transaction", () => {
      const prompt = buildTransactionChatPrompt({
        description: "Grab Taxi",
        amount: "18.20",
        currency: "SGD",
        date: "2024-03-12",
      });
      expect(prompt).toBe(
        "Please analyze this transaction: 'Grab Taxi', amount: 18.20 SGD on 2024-03-12. What is the recommended accounting category and is it tax deductible?"
      );
    });

    it("handles missing transaction fields gracefully", () => {
      const prompt = buildTransactionChatPrompt({});
      expect(prompt).toBe(
        "Please analyze this transaction: 'Untitled Transaction', amount: N/A on unspecified date. What is the recommended accounting category and is it tax deductible?"
      );
    });

    it("builds correct prompt for statement", () => {
      const prompt = buildStatementChatPrompt({
        filename: "DBS_March_2024.pdf",
        institution: "DBS",
        periodStart: "2024-03-01",
        periodEnd: "2024-03-31",
        transactionCount: 42,
      });
      expect(prompt).toBe(
        "Please review this statement: 'DBS_March_2024.pdf' (DBS, 2024-03-01 to 2024-03-31) with 42 transactions. Highlight major expense categories and any potential anomalies."
      );
    });
  });

  describe("StatementAiAssistantButton Component", () => {
    it("renders transaction button and routes to /chat on click", () => {
      render(
        <StatementAiAssistantButton
          transaction={{
            description: "Flight to Tokyo",
            amount: "650.00",
            currency: "USD",
            date: "2024-04-01",
          }}
        />
      );

      const button = screen.getByRole("button", { name: "Ask AI about transaction" });
      expect(button).toBeInTheDocument();

      fireEvent.click(button);
      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining("/chat?prompt=")
      );
      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining("Flight%20to%20Tokyo")
      );
    });

    it("renders statement button with custom label and calls onNavigate callback", () => {
      const onNavigate = vi.fn();
      render(
        <StatementAiAssistantButton
          statement={{
            filename: "OCBC_Statement.pdf",
            institution: "OCBC",
            transactionCount: 15,
          }}
          label="Ask Advisor"
          onNavigate={onNavigate}
        />
      );

      const button = screen.getByRole("button", { name: "Ask Advisor" });
      expect(button).toBeInTheDocument();

      fireEvent.click(button);
      expect(onNavigate).toHaveBeenCalledWith(
        expect.stringContaining("OCBC_Statement.pdf")
      );
      expect(mockPush).not.toHaveBeenCalled();
    });

    it("is disabled when neither statement nor transaction is provided", () => {
      render(<StatementAiAssistantButton />);
      const button = screen.getByTestId("statement-ai-assistant-button");
      expect(button).toBeDisabled();
    });
  });
});
