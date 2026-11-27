import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InvestmentPerformanceSchedule } from "@/components/portfolio/InvestmentPerformanceSchedule";
import { has, IPS_CURR, IPS_CURR_TEXTS, IPS_STALE, IPS_STALE_TEXTS, noTxt, txt } from "./helpers/packageTestFixtures";

describe("InvestmentPerformanceSchedule", () => {
  it("AC8.13.92 renders loading, error, stale, and current states", () => {
    const { rerender } = render(<InvestmentPerformanceSchedule isLoading />);
    expect(txt("Investment Performance Report Schedule")).toBeInTheDocument();
    expect(document.querySelector("[aria-busy='true']")).toBeInTheDocument();
    rerender(<InvestmentPerformanceSchedule error={new Error("down")} />);
    expect(txt("Unable to load investment performance schedule")).toBeInTheDocument();
    rerender(<InvestmentPerformanceSchedule schedule={IPS_STALE} />);
    has(IPS_STALE_TEXTS);
    expect(txt("-10.00%")).toHaveClass("text-[var(--error)]");
    expect(txt("+8.25%")).toHaveClass("text-[var(--success)]");
    expect(screen.getAllByText("N/A").length).toBeGreaterThanOrEqual(2);
    expect(txt("-1.50%")).toHaveClass("text-[var(--error)]");
    noTxt("Notes");
    rerender(<InvestmentPerformanceSchedule schedule={IPS_CURR as never} />);
    expect(screen.getAllByText("0.00%").length).toBeGreaterThanOrEqual(2);
    has(IPS_CURR_TEXTS); noTxt(/Stale holdings:/);
    expect(screen.getByText("investment_performance")).not.toHaveClass("hidden");
  });
});
