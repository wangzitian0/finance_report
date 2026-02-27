import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { BarChart } from "@/components/charts/BarChart"
import { PieChart } from "@/components/charts/PieChart"
import { TrendChart } from "@/components/charts/TrendChart"

describe("Chart components", () => {
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
    expect(screen.getByText("Cash")).toBeInTheDocument()
    expect(screen.queryByText("Zero")).toBeNull()
  })

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
})
