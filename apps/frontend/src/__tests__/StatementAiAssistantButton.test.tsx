import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  StatementAiAssistantButton,
  buildStatementChatPrompt,
  buildTransactionChatPrompt,
} from "@/components/statements/StatementAiAssistantButton";
import { PENDING_CHAT_PROMPT_KEY } from "@/components/ChatPageClient";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// AC-advisor.fe-chat.1
describe("StatementAiAssistantButton & Prompt Helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
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

    it("builds correct prompt for statement with both dates", () => {
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

    it("builds statement prompt with only start or only end or neither", () => {
      const promptStart = buildStatementChatPrompt({
        filename: "Statement.pdf",
        periodStart: "2024-01-01",
      });
      expect(promptStart).toContain("2024-01-01");

      const promptEnd = buildStatementChatPrompt({
        periodEnd: "2024-01-31",
      });
      expect(promptEnd).toContain("2024-01-31");

      const promptEmpty = buildStatementChatPrompt({});
      expect(promptEmpty).toContain("unspecified period");
      expect(promptEmpty).toContain("an unknown number of transactions");
    });
  });

  describe("StatementAiAssistantButton Component", () => {
    it("renders transaction button and routes to /chat on click saving to sessionStorage", () => {
      render(
        <StatementAiAssistantButton
          transaction={{
            description: "Flight to Tokyo",
            amount: "650.00",
            currency: "USD",
            date: "2024-04-01",
          }}
          variant="primary"
        />
      );

      const button = screen.getByRole("button", { name: "Ask AI about transaction" });
      expect(button).toBeInTheDocument();
      expect(button).toHaveClass("btn-primary");

      fireEvent.click(button);
      expect(sessionStorage.getItem(PENDING_CHAT_PROMPT_KEY)).toContain("Flight to Tokyo");
      expect(mockPush).toHaveBeenCalledWith("/chat");
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
          variant="ghost"
          icon="message"
          onNavigate={onNavigate}
        />
      );

      const button = screen.getByRole("button", { name: "Ask Advisor" });
      expect(button).toBeInTheDocument();
      expect(button).toHaveClass("btn-ghost");

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
      fireEvent.click(button);
      expect(mockPush).not.toHaveBeenCalled();
    });
  });
});
