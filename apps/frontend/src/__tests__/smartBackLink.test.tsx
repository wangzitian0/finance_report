// AC-reporting.fe-report-surfaces.2: SmartBackLink dynamic router navigation
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SmartBackLink } from "@/components/ui/SmartBackLink";

const navigationState = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigationState.searchParams,
}));

describe("SmartBackLink (BUG-10 dynamic back navigation)", () => {
  beforeEach(() => {
    navigationState.searchParams = new URLSearchParams();
  });

  it("renders default fallback link to dashboard with meaningful label", () => {
    render(<SmartBackLink />);
    const link = screen.getByTestId("smart-back-link");
    expect(link).toHaveAttribute("href", "/dashboard");
    expect(screen.getByText("Back to Dashboard")).toBeInTheDocument();
  });

  it("renders custom fallback label and href when provided", () => {
    render(<SmartBackLink fallbackHref="/reports" fallbackLabel="Back to Reports" />);
    const link = screen.getByTestId("smart-back-link");
    expect(link).toHaveAttribute("href", "/reports");
    expect(screen.getByText("Back to Reports")).toBeInTheDocument();
  });

  it("renders children when provided", () => {
    render(<SmartBackLink fallbackHref="/reports">Return to Reports</SmartBackLink>);
    expect(screen.getByText("Return to Reports")).toBeInTheDocument();
  });

  it("routes to attention queue when attention origin is present", () => {
    navigationState.searchParams = new URLSearchParams("from=attention");
    render(<SmartBackLink fallbackHref="/reports" fallbackLabel="Back to Reports" />);
    const link = screen.getByTestId("smart-back-link");
    expect(link).toHaveAttribute("href", "/attention");
    expect(screen.getByText("Back to Attention queue")).toBeInTheDocument();

    // Click should not prevent default
    fireEvent.click(link);
  });

  it("routes to explicit return_to target", () => {
    navigationState.searchParams = new URLSearchParams("return_to=%2Fcustom%2Fpath");
    render(<SmartBackLink fallbackHref="/reports" />);
    const link = screen.getByTestId("smart-back-link");
    expect(link).toHaveAttribute("href", "/custom/path");
    expect(screen.getByText("Back")).toBeInTheDocument();

    // Click should not prevent default
    fireEvent.click(link);
  });

  it("calls window.history.back when history length exceeds 2", () => {
    const historyBackSpy = vi.spyOn(window.history, "back").mockImplementation(() => {});
    Object.defineProperty(window.history, "length", { value: 3, configurable: true });

    render(<SmartBackLink fallbackHref="/reports" />);
    const link = screen.getByTestId("smart-back-link");
    fireEvent.click(link);

    expect(historyBackSpy).toHaveBeenCalled();
    historyBackSpy.mockRestore();
  });
});
