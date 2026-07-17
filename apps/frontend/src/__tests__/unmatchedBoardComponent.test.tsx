import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UnmatchedBoard from "@/components/reconciliation/UnmatchedBoard";
import { apiFetch } from "@/lib/api";

const navigationState = vi.hoisted(() => ({ searchParams: new URLSearchParams() }));

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => navigationState.searchParams }));

const unmatchedItem = {
  id: "u1",
  statement_id: "s1",
  txn_date: "2026-01-11",
  description: "Card payment",
  amount: "88.00",
  currency: "SGD",
  direction: "OUT",
  status: "unmatched",
};

const expenseAccount = {
  id: "expense-1",
  name: "Expense - Dining",
  type: "EXPENSE",
  currency: "SGD",
  is_active: true,
};

describe("UnmatchedBoard", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  const mockInitialLoad = () => {
    mockedApiFetch
      .mockResolvedValueOnce({ items: [unmatchedItem], total: 1 })
      .mockResolvedValueOnce({ items: [expenseAccount], total: 1 });
  };

  beforeEach(() => {
    mockedApiFetch.mockReset();
    navigationState.searchParams = new URLSearchParams();
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    });
  });

  it("AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action", async () => {
    mockInitialLoad();
    mockedApiFetch
      .mockResolvedValueOnce({ id: "je1", entry_date: "2026-01-11", memo: "Card payment", status: "posted", total_amount: "88.00" })
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [expenseAccount], total: 1 });

    render(<UnmatchedBoard />);

    await screen.findByRole("heading", { name: "Unmatched Transactions" });
    await screen.findByRole("option", { name: /Expense - Dining/ });
    fireEvent.change(screen.getByLabelText("Counter account"), { target: { value: expenseAccount.id } });
    fireEvent.change(screen.getByLabelText("Report category"), { target: { value: "DINING" } });
    fireEvent.change(screen.getByLabelText("Review rationale"), { target: { value: "Receipt and merchant reviewed." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and Post" }));

    await waitFor(() => {
      const reviewedCall = mockedApiFetch.mock.calls.find(
        ([path]) => path === "/api/reconciliation/unmatched/u1/reviewed-disposition",
      );
      expect(reviewedCall).toBeDefined();
      expect((reviewedCall?.[1] as RequestInit).method).toBe("POST");
      expect(JSON.parse((reviewedCall?.[1] as RequestInit).body as string)).toEqual({
        intent: "expense",
        counter_account_id: "expense-1",
        category: "DINING",
        rationale: "Receipt and merchant reviewed.",
      });
    });
    const postedEntryId = await screen.findByText("je1");
    expect(postedEntryId.parentElement).toHaveTextContent("Posted reviewed entry je1");
    expect(screen.queryByRole("button", { name: /Create Entry/i })).not.toBeInTheDocument();
  });

  it("routes transfers to reconciliation instead of allowing a P&L posting", async () => {
    mockInitialLoad();
    render(<UnmatchedBoard />);

    await screen.findByRole("heading", { name: "Unmatched Transactions" });
    fireEvent.change(screen.getByLabelText("Economic intent"), { target: { value: "transfer" } });

    expect(screen.getByText(/must be paired in the reconciliation workbench/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and Post" })).not.toBeInTheDocument();
  });

  it("AC22.11.3 returns attention-origin unmatched review to the attention queue", async () => {
    navigationState.searchParams = new URLSearchParams("from=attention");
    mockInitialLoad();
    render(<UnmatchedBoard />);

    const backLink = await screen.findByRole("link", { name: /Back to Attention queue/i });
    expect(backLink).toHaveAttribute("href", "/attention");
  });

  it("AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision", async () => {
    mockInitialLoad();
    render(<UnmatchedBoard />);

    await screen.findByRole("heading", { name: "Unmatched Transactions" });
    fireEvent.click(screen.getByRole("button", { name: "Flag local" }));
    expect(screen.getByRole("button", { name: "Unflag local" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide locally" }));
    await waitFor(() => expect(screen.queryAllByText("Card payment")).toHaveLength(0));
  });

  it("surfaces a reviewed-disposition failure without fabricating a success state", async () => {
    mockInitialLoad();
    mockedApiFetch.mockRejectedValueOnce(new Error("counter account is incompatible"));
    render(<UnmatchedBoard />);

    await screen.findByRole("heading", { name: "Unmatched Transactions" });
    await screen.findByRole("option", { name: /Expense - Dining/ });
    fireEvent.change(screen.getByLabelText("Counter account"), { target: { value: expenseAccount.id } });
    fireEvent.change(screen.getByLabelText("Report category"), { target: { value: "DINING" } });
    fireEvent.change(screen.getByLabelText("Review rationale"), { target: { value: "Reviewed source evidence." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and Post" }));

    expect(await screen.findByText("counter account is incompatible")).toBeInTheDocument();
    expect(screen.queryByText(/Posted reviewed entry/)).not.toBeInTheDocument();
  });

  // AC-reconciliation.fe-remainder-reconciliation.1
  it("AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        items: [{ ...unmatchedItem, id: "u-precise", amount: "12345678901234567890.12", currency: "USD" }],
        total: 1,
      })
      .mockResolvedValueOnce({ items: [], total: 0 });
    render(<UnmatchedBoard />);

    expect(await screen.findAllByText("$12,345,678,901,234,567,890.12")).toHaveLength(2);
  });
});
