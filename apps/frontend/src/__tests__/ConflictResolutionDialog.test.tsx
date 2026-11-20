import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConflictResolutionDialog } from "@/components/statements/StatementReview";
import { clk, has } from "./helpers/statementTestFixtures";

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

  it("AC16.34.3 renders one confirmation for all candidates, links nothing, and disables while resolving (#2958)", () => {
    const onResolve = vi.fn();
    const dups = [1, 2, 3].map((n) => ({ id: `d${n}`, description: `Dup ${n}`, txn_date: "2024-01-01", amount: "10.00" }));
    const xfers = [1, 2].map((n) => ({ id: `x${n}`, description: `Transfer ${n}`, txn_date: "2024-01-02", amount: "20.00" }));
    const { rerender } = render(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={dups} transferPairCandidates={xfers} onResolve={onResolve} />);
    has(["Duplicate Candidates", "Dup 3", "Transfer Pair Candidates", "Transfer 2", "This confirmation links no rows. Transfer pairs are matched in reconciliation."]);
    const actions = screen.getAllByRole("button").filter((b) => !/close/i.test(b.textContent ?? "") && !/close/i.test(b.getAttribute("aria-label") ?? ""));
    expect(actions).toHaveLength(1);
    expect(screen.queryByText("Link Pair")).toBeNull();
    fireEvent.click(actions[0]);
    expect(onResolve).toHaveBeenCalledTimes(1);
    expect(onResolve).toHaveBeenCalledWith();
    rerender(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={dups} transferPairCandidates={[]} onResolve={onResolve} isResolving />);
    const pending = screen.getByText("Confirming…");
    expect(pending).toBeDisabled();
    fireEvent.click(pending);
    expect(onResolve).toHaveBeenCalledTimes(1);
  });

  it("lists a match with an approved statement of another account and keeps one confirmation (#2917)", () => {
    const onResolve = vi.fn();
    const other = [{ statement_id: "s9", account_name: "DBS From PDF", matched_rows: 3, total_rows: 3 }];
    render(<ConflictResolutionDialog isOpen onClose={onClose} duplicateCandidates={[]} transferPairCandidates={[]} otherStatementMatches={other} onResolve={onResolve} />);
    has(["Same rows on another account", "DBS From PDF"]);
    expect(screen.getByRole("dialog")).toHaveTextContent("3 of 3 rows equal an approved statement of DBS From PDF");
    expect(screen.queryByText("No conflicts detected for this statement.")).toBeNull();
    expect(screen.getByRole("link", { name: "Open that statement" })).toHaveAttribute("href", "/statements/s9");
    fireEvent.click(screen.getByText("These rows are different transactions. Continue."));
    expect(onResolve).toHaveBeenCalledTimes(1);
  });
});
