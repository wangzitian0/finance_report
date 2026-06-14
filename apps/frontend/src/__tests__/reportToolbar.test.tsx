import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AiPromptAction, ReportToolbar } from "@/components/reports/ReportToolbar";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  apiDownload: vi.fn(),
}));

describe("ReportToolbar", () => {
  it("AC5.33.4 renders AI prompt, home link, and CSV export", () => {
    render(
      <ReportToolbar
        aiPrompt="Explain my balance sheet"
        exportPath="/api/reports/export?report_type=balance-sheet&format=csv&currency=SGD"
      />,
    );

    const aiLink = screen.getByRole("link", { name: "AI Interpretation" });
    expect(aiLink).toHaveAttribute(
      "href",
      `/chat?prompt=${encodeURIComponent("Explain my balance sheet")}`,
    );
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });

  it("AC5.33.5 links to chat with url-encoded prompt", () => {
    render(<AiPromptAction prompt="Summarize income from 2026-01-01 to 2026-06-30" />);

    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      `/chat?prompt=${encodeURIComponent("Summarize income from 2026-01-01 to 2026-06-30")}`,
    );
  });
});
