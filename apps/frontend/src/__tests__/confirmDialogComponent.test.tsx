import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { btn, clk, has } from "./helpers/statementTestFixtures";

describe("ConfirmDialog component", () => {
  it("AC16.19.7 handles required/optional input and confirm/cancel", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    const { rerender } = render(<ConfirmDialog isOpen title="Reject" message="Provide reason" input={{ required: true, label: "Reason" }} confirmLabel="Reject" onConfirm={onConfirm} onCancel={onCancel} />);
    has(["Reason", "*"]);
    const b = btn("Reject") as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    fireEvent.click(b);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "bad data" } });
    expect(b.disabled).toBe(false);
    fireEvent.click(b);
    expect(onConfirm).toHaveBeenCalledWith("bad data");
    clk("Cancel");
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(<ConfirmDialog isOpen title="T" message="M" input={{}} onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "note" } });
    clk("Confirm");
    expect(onConfirm).toHaveBeenCalledWith("note");
  });

  it("AC16.19.8/16/17 AC16.30.4 handles ARIA, danger, children, loading lock, closed, and focus trap", () => {
    const onCancel = vi.fn();
    const { container, rerender } = render(<ConfirmDialog isOpen title="Approve" message="Proceed" confirmVariant="danger" confirmLabel="Delete" input={{}} onConfirm={vi.fn()} onCancel={onCancel}><p>Extra</p></ConfirmDialog>);
    const dlg = screen.getByRole("dialog");
    expect(dlg).toHaveAttribute("aria-modal", "true");
    expect(dlg).toHaveAttribute("aria-labelledby");
    has(["Extra"]);
    expect(btn("Delete").className).toContain("--error");
    const els = dlg.querySelectorAll<HTMLElement>("button, textarea");
    const first = els[0], last = els[els.length - 1];
    first?.focus(); fireEvent.keyDown(dlg, { key: "Tab", shiftKey: true }); expect(document.activeElement).toBe(last);
    last?.focus(); fireEvent.keyDown(dlg, { key: "Tab", shiftKey: false }); expect(document.activeElement).toBe(first);
    first?.focus(); fireEvent.keyDown(dlg, { key: "a" }); expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(container.querySelector("[aria-hidden='true']")!);
    expect(onCancel).toHaveBeenCalledTimes(2);
    rerender(<ConfirmDialog isOpen loading title="W" message="W" onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(container.querySelector("[aria-hidden='true']")!);
    expect(onCancel).toHaveBeenCalledTimes(2);
    has(["Processing..."]);
    rerender(<ConfirmDialog isOpen={false} title="T" message="M" onConfirm={vi.fn()} onCancel={onCancel} />);
    expect(container.querySelector("[role='dialog']")).toBeNull();
  });
});
