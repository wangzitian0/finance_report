import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AiPromptAction, ReportToolbar } from "@/components/reports/ReportPageShell";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("ReportToolbar", () => {
  // AC-reporting.fe-viz-reports.16
  it("AC5.33.4 renders the AI prompt and the caller-provided export control, without a Home link", () => {
    // The export control is caller-provided (#751: this primitive must not import
    // API/transport code). The page wires the actual export behavior in.
    const onExport = vi.fn();
    render(
      <ReportToolbar
        aiPrompt="Explain my balance sheet"
        exportControl={
          <button type="button" onClick={onExport}>
            Export CSV
          </button>
        }
      />,
    );

    const aiLink = screen.getByRole("link", { name: "AI Interpretation" });
    expect(aiLink).toHaveAttribute(
      "href",
      `/chat?prompt=${encodeURIComponent("Explain my balance sheet")}`,
    );
    // The toolbar sits inside a /reports tab: the app shell navigates to Home.
    expect(screen.queryByRole("link", { name: "Home" })).toBeNull();

    const exportButton = screen.getByRole("button", { name: "Export CSV" });
    expect(exportButton).toBeInTheDocument();
    fireEvent.click(exportButton);
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  // AC-reporting.fe-viz-reports.17
  it("AC5.33.5 links to chat with url-encoded prompt", () => {
    render(<AiPromptAction prompt="Summarize income from 2026-01-01 to 2026-06-30" />);

    expect(screen.getByRole("link", { name: "AI Interpretation" })).toHaveAttribute(
      "href",
      `/chat?prompt=${encodeURIComponent("Summarize income from 2026-01-01 to 2026-06-30")}`,
    );
  });
});
