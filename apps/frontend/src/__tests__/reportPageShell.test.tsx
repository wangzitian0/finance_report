import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReportPageShell } from "@/components/reports/ReportPageShell";

describe("ReportPageShell", () => {
  it("AC5.33.1 renders title, description, toolbar, and body content", () => {
    render(
      <ReportPageShell
        title="Balance Sheet"
        description="Assets = Liabilities + Equity"
        toolbar={<button type="button">Export CSV</button>}
        loadingLabel="Loading balance sheet"
      >
        <div>Report body</div>
      </ReportPageShell>,
    );

    expect(screen.getByRole("heading", { name: "Balance Sheet" })).toBeInTheDocument();
    expect(screen.getByText("Assets = Liabilities + Equity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.getByText("Report body")).toBeInTheDocument();
  });

  it("AC5.33.2 shows loading skeleton while loading", () => {
    render(
      <ReportPageShell title="Cash Flow" loadingLabel="Loading cash flow" isLoading>
        <div>Report body</div>
      </ReportPageShell>,
    );

    expect(screen.getByRole("status", { name: "Loading cash flow" })).toBeInTheDocument();
    expect(screen.queryByText("Report body")).not.toBeInTheDocument();
  });

  it("AC5.33.3 shows error message and retries on click", () => {
    const onRetry = vi.fn();
    render(
      <ReportPageShell
        title="Income Statement"
        loadingLabel="Loading income statement"
        isError
        errorMessage="Boom"
        onRetry={onRetry}
      >
        <div>Report body</div>
      </ReportPageShell>,
    );

    expect(screen.getByText("Boom")).toBeInTheDocument();
    expect(screen.queryByText("Report body")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
