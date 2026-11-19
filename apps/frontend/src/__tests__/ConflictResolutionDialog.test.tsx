import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConflictResolutionDialog } from "@/components/statements/StatementReview";
import { clk, has } from "./helpers/statementTestFixtures";

const dup = [{ id: "d1", description: "Dup One", txn_date: "2024-01-01", amount: "10.00" }];
const xfer = [{ id: "x1", description: "Transfer A", txn_date: "2024-01-02", amount: "20.00" }];

describe("ConflictResolutionDialog", () => {
  const onClose = vi.fn();
  beforeEach(() => { vi.clearAllMocks(); });

  it("closes empty dialog via overlay, Close, Close modal, and Escape", () => {
    render(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={[]} transferPairCandidates={[]} />);
    has(["No conflicts detected for this statement."]);
    fireEvent.click(document.querySelector(".fixed.inset-0 > [aria-hidden='true']")!);
    fireEvent.click(screen.getAllByRole("button", { name: /Close/i }).find((b) => b.textContent?.trim() === "Close")!);
    clk("Close modal");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(4);
  });

  it("AC16.34.3 renders candidates, fires actions, and disables while resolving", () => {
    const onResolve = vi.fn();
    const { rerender } = render(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={dup} transferPairCandidates={xfer} onResolve={onResolve} />);
    has(["Duplicate Candidates", "Dup One", "Transfer Pair Candidates", "Transfer A"]);
    fireEvent.click(screen.getByText("Resolve"));
    expect(onResolve).toHaveBeenCalledWith("confirm_distinct");
    fireEvent.click(screen.getByText("Link Pair"));
    expect(onResolve).toHaveBeenCalledWith("link_transfer");
    rerender(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={dup} transferPairCandidates={[]} onResolve={onResolve} isResolving />);
    const r = screen.getByText("Resolving…");
    expect(r).toBeDisabled();
    fireEvent.click(r);
    expect(onResolve).toHaveBeenCalledTimes(2);
  });
});
