import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { OpeningBalanceWarningBanner } from "@/components/reports/OpeningBalanceWarningBanner";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

describe("OpeningBalanceWarningBanner (#1486)", () => {
  it("renders nothing when there are no warnings", () => {
    const { container } = render(<OpeningBalanceWarningBanner warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when warnings is undefined", () => {
    const { container } = render(<OpeningBalanceWarningBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the backend message and a CTA to the guided opening-balance flow", () => {
    render(
      <OpeningBalanceWarningBanner
        warnings={[{ type: "missing_opening_balance", message: "Record opening balances to trust this total." }]}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Record opening balances to trust this total.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /set opening balances/i })).toHaveAttribute("href", "/accounts");
  });

  it("falls back to a default message when the warning carries none", () => {
    render(<OpeningBalanceWarningBanner warnings={[{ type: "missing_opening_balance" }]} />);

    expect(screen.getByText(/reflect only/i)).toBeInTheDocument();
  });
});
