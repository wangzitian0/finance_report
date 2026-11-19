import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HoldingsTable } from "@/components/portfolio/Holdings";
import { has, HT_GROUPED, HT_PAIR, HT_PROVENANCE, HT_ZERO_PNL, noTxt, txt } from "./helpers/packageTestFixtures";

describe("HoldingsTable", () => {
  it("renders empty, fractional, grouped, disposed, zero-PnL, sector, and unknown-account rows", () => {
    const { rerender } = render(<HoldingsTable holdings={[]} />);
    expect(txt("No holdings found")).toBeInTheDocument();
    rerender(<HoldingsTable holdings={HT_PAIR} />);
    has(["10.50", "FOO"]); noTxt("GONE");
    rerender(<HoldingsTable holdings={HT_PAIR} showDisposed />);
    expect(txt("GONE")).toBeInTheDocument();
    rerender(<HoldingsTable holdings={HT_GROUPED} />);
    has(["BrokerB", /\$210\.00/, "-16.67%"]);
    rerender(<HoldingsTable holdings={HT_ZERO_PNL} />);
    has(["0.00%", /Technology/, "Unknown"]);
  });

  it("AC22.10.1 AC22.13.2 #1487 renders provenance badges and native-currency notes", () => {
    render(<HoldingsTable holdings={HT_PROVENANCE} />);
    expect(screen.getAllByText("Imported")).toHaveLength(1);
    expect(txt("Manual")).toHaveClass("badge-warning");
    expect(txt("Derived")).toHaveClass("badge-muted");
    noTxt("Unknown");
    expect(txt(/HKD-denominated/)).toBeInTheDocument();
  });
}); // AC-portfolio.fe-ia-portfolio.1
