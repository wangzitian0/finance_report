import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SmartBackLink } from "@/components/ui/SmartBackLink";

const mockBack = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ back: mockBack }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("SmartBackLink (BUG-10 dynamic back navigation)", () => {
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
});
