import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { BarChart } from "@/components/charts/BarChart"
import { PieChart } from "@/components/charts/PieChart"
import { TrendChart } from "@/components/charts/TrendChart"

describe("Chart components", () => {
  // AC-reporting.fe-report-surfaces.19
  it("AC16.19.10 bar chart and pie chart render labels and filtered segments", () => {
    render(
      <div>
        <BarChart
          items={[
            { label: "Jan", income: 2000, expense: 1200 },
            { label: "Feb", income: 1500, expense: 900 },
          ]}
        />
        <PieChart
          centerLabel="Allocation"
          segments={[
            { label: "Cash", value: 60, color: "#00aa00" },
            { label: "Stocks", value: 40, color: "#0000aa" },
            { label: "Zero", value: 0, color: "#cccccc" },
          ]}
        />
      </div>,
    )

    expect(screen.getByText("Jan")).toBeInTheDocument()
    expect(screen.getByText("Feb")).toBeInTheDocument()
    expect(screen.getByText("Allocation")).toBeInTheDocument()
    expect(screen.getAllByText("Cash")[0]).toBeInTheDocument()
    expect(screen.queryByText("Zero")).toBeNull()
  })

  // AC-reporting.fe-report-surfaces.20
  it("AC16.19.11 trend chart renders point labels and svg paths", () => {
    const { container } = render(
      <TrendChart
        points={[
          { label: "Q1", value: 100 },
          { label: "Q2", value: 160 },
          { label: "Q3", value: 130 },
        ]}
      />,
    )

    expect(screen.getByRole("img", { name: "Trend chart" })).toBeInTheDocument()
    expect(screen.getByText("Q1")).toBeInTheDocument()
    expect(screen.getByText("Q2")).toBeInTheDocument()
    expect(screen.getByText("Q3")).toBeInTheDocument()
    expect(container.querySelectorAll("path").length).toBeGreaterThan(1)
    expect(container.querySelectorAll("circle").length).toBe(3)
  })

  // AC-reporting.2548.3
  it("AC-reporting.2548.3 renders axis scale bounds, formatted values, and percentage shares across chart components", () => {
    render(
      <div>
        <BarChart
          items={[
            { label: "Jan", income: 4000, expense: 2500 },
            { label: "Feb", income: 3000, expense: 1800 },
          ]}
        />
        <PieChart
          centerLabel="Assets"
          segments={[
            { label: "Cash", value: 7500, color: "#00aa00" },
            { label: "Equities", value: 2500, color: "#0000aa" },
          ]}
        />
        <TrendChart
          points={[
            { label: "2026-01", value: 12000 },
            { label: "2026-02", value: 15500 },
          ]}
        />
      </div>,
    )

    expect(screen.getByTestId("bar-chart-axis-scale")).toHaveTextContent("4.0k")
    expect(screen.getByTestId("bar-chart-net-Jan")).toHaveTextContent("+1.5k")
    expect(screen.getByTestId("pie-segment-share-Cash")).toHaveTextContent("75%")
    expect(screen.getByTestId("pie-segment-share-Equities")).toHaveTextContent("25%")
    expect(screen.getByTestId("trend-axis-scale")).toHaveTextContent("15.5k")
    expect(screen.getByTestId("trend-axis-scale")).toHaveTextContent("12.0k")
  })
})
