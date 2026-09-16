import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LowConfidenceReviewModal } from "@/components/review/LowConfidenceReviewModal";
import type { BankStatementTransaction } from "@/lib/types";

const mockApiOperation = vi.fn();
vi.mock("@/lib/api-client", () => ({
  apiOperation: (...args: unknown[]) => mockApiOperation(...args),
}));

const mockShowToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

vi.mock("@/lib/audit/money", () => ({
  formatCurrencyLocale: (amount: unknown, currency: string) => `${currency} ${String(amount)}`,
}));

const mockTransaction: BankStatementTransaction = {
  id: "txn-123",
  statement_id: "stmt-456",
  txn_date: "2024-03-15",
  description: "Starbucks Coffee #998",
  amount: "5.50",
  direction: "OUT",
  currency: "SGD",
  confidence: "low",
  confidence_tier: "LOW",
  created_at: "",
  updated_at: "",
  status: "pending",
};

// AC-extraction.fe-stage1-review.7
describe("LowConfidenceReviewModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when isOpen is false or transaction is null", () => {
    const { rerender } = render(
      <LowConfidenceReviewModal
        isOpen={false}
        onClose={vi.fn()}
        transaction={mockTransaction}
      />
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    rerender(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={vi.fn()}
        transaction={null}
      />
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders transaction details and confidence badge when open", () => {
    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={vi.fn()}
        transaction={mockTransaction}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Review Low-Confidence Transaction")).toBeInTheDocument();
    expect(screen.getByText("Starbucks Coffee #998")).toBeInTheDocument();
    expect(screen.getByText("-SGD 5.50")).toBeInTheDocument();
    expect(screen.getByText(/2024-03-15/)).toBeInTheDocument();
  });

  it("selects category via quick category chips", async () => {
    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={vi.fn()}
        transaction={mockTransaction}
      />
    );

    const diningChip = screen.getByRole("button", { name: "Dining" });
    fireEvent.click(diningChip);

    const input = screen.getByLabelText(/Classification Category/i) as HTMLInputElement;
    expect(input.value).toBe("Dining");
  });

  it("submits correction via apiOperation on save", async () => {
    mockApiOperation.mockResolvedValueOnce({
      id: "corr-1",
      transaction_id: "txn-123",
      corrected_category: "Dining",
    });

    const onClose = vi.fn();
    const onSuccess = vi.fn();

    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={onClose}
        transaction={mockTransaction}
        onSuccess={onSuccess}
      />
    );

    const diningChip = screen.getByRole("button", { name: "Dining" });
    fireEvent.click(diningChip);

    const saveButton = screen.getByRole("button", { name: /Save Correction/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockApiOperation).toHaveBeenCalledWith("create_correction_corrections_post", {
        body: {
          transaction_id: "txn-123",
          corrected_category: "Dining",
        },
      });
      expect(mockShowToast).toHaveBeenCalledWith('Category updated to "Dining"', "success");
      expect(onSuccess).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("shows error if saving with empty category", async () => {
    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={vi.fn()}
        transaction={mockTransaction}
      />
    );

    const input = screen.getByLabelText(/Classification Category/i);
    await userEvent.clear(input);

    const form = input.closest("form")!;
    fireEvent.submit(form);

    expect(await screen.findByRole("alert")).toHaveTextContent("Please select or enter a category.");
    expect(mockApiOperation).not.toHaveBeenCalled();
  });

  it("renders Ask AI Assistant link with encoded prompt", () => {
    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={vi.fn()}
        transaction={mockTransaction}
      />
    );

    const askAiLink = screen.getByRole("link", { name: /Ask AI Assistant/i });
    expect(askAiLink).toBeInTheDocument();
    expect(askAiLink).toHaveAttribute("href", expect.stringContaining("/chat?prompt="));
    expect(askAiLink).toHaveAttribute("href", expect.stringContaining("Starbucks"));
  });

  it("closes modal on Escape key", () => {
    const onClose = vi.fn();
    render(
      <LowConfidenceReviewModal
        isOpen={true}
        onClose={onClose}
        transaction={mockTransaction}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
