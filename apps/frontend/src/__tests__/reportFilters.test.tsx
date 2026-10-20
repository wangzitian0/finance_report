import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CurrencyFilterControl,
  DateFilterControl,
  PeriodPresetFilterControl,
} from "@/components/reports/ReportFilters";

describe("Report filter controls", () => {
  // AC-reporting.fe-viz-reports.18
  it("AC5.34.1 renders labelled date input and emits change", () => {
    const onChange = vi.fn();
    render(<DateFilterControl label="As of date" value="2026-06-30" onChange={onChange} />);

    const input = screen.getByLabelText("As of date");
    expect(input).toHaveValue("2026-06-30");

    fireEvent.change(input, { target: { value: "2026-07-01" } });
    expect(onChange).toHaveBeenCalledWith("2026-07-01");
  });

  // AC-reporting.fe-viz-reports.19
  it("AC5.34.2 renders currency options and emits change", () => {
    const onChange = vi.fn();
    render(
      <CurrencyFilterControl
        value="SGD"
        currencies={["SGD", "USD", "EUR"]}
        onChange={onChange}
      />,
    );

    const select = screen.getByLabelText("Currency");
    expect(select).toHaveValue("SGD");
    expect(screen.getByRole("option", { name: "USD" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "EUR" })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "USD" } });
    expect(onChange).toHaveBeenCalledWith("USD");
  });

  it("renders quick period presets and emits resolved date range", () => {
    window.sessionStorage.setItem("finance_report.cockpit_period", "1Q");
    const onSelectRange = vi.fn();
    render(<PeriodPresetFilterControl onSelectRange={onSelectRange} defaultPreset="1Y" />);

    expect(screen.getByRole("button", { name: "Period 1Q" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Period YTD" }));
    expect(screen.getByRole("button", { name: "Period YTD" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(onSelectRange).toHaveBeenCalledWith(
      expect.objectContaining({
        startDate: expect.stringMatching(/^\d{4}-01-01$/),
        endDate: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      }),
      "YTD",
    );
    expect(window.sessionStorage.getItem("finance_report.cockpit_period")).toBe("YTD");
    window.sessionStorage.removeItem("finance_report.cockpit_period");
  });
});
