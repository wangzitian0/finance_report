import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DetailDialog, Sheet } from "@/components/ui/Overlay";
it.each([[Sheet, /Close panel/i], [DetailDialog, /Close modal/i]] as const)("AC16.30.4 %#", (Comp, closeRe) => {
  expect(render(<Comp isOpen={false} onClose={vi.fn()} title="T">x</Comp>).container.querySelector("[role='dialog']")).toBeNull();
  const onClose = vi.fn();
  const { container } = render(<Comp isOpen onClose={onClose} title="Title"><p>abc</p></Comp>);
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(screen.getByText("Title")).toBeInTheDocument();
  expect(screen.getByText("abc")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: closeRe }));
  fireEvent.click(container.querySelector("[aria-hidden='true']")!);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(3);
});
