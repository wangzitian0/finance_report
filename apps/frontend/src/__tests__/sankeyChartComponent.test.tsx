import { render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

let capturedProps: { option?: Record<string, unknown>; style?: { height?: string; width?: string } } | null = null
let observerCallback: ((mutations: MutationRecord[]) => void) | null = null

vi.mock("next/dynamic", () => ({
  default: () => {
    const MockChart = (props: { option: Record<string, unknown>; style: { height: string; width: string } }) => {
      capturedProps = props
      return <div data-testid="mock-echarts" />
    }
    return MockChart
  },
}))

import { SankeyChart } from "@/components/charts/SankeyChart"

describe("SankeyChart", () => {
  const colors: Record<string, string> = {
    "--success": "#1f9d55",
    "--error": "#e11d48",
    "--accent": "#2563eb",
    "--warning": "#f59e0b",
    "--foreground": "#0f172a",
    "--foreground-muted": "#64748b",
  }

  beforeEach(() => {
    capturedProps = null
    observerCallback = null

    vi.stubGlobal(
      "getComputedStyle",
      vi.fn(() => ({
        getPropertyValue: (name: string) => colors[name] ?? "#888",
      })),
    )

    vi.stubGlobal(
      "MutationObserver",
      class {
        constructor(cb: (mutations: MutationRecord[]) => void) {
          observerCallback = cb
        }
        observe() {}
        disconnect() {}
      },
    )
  })

  it("AC16.21.7 renders empty-state option when no series data is provided", () => {
    render(<SankeyChart title="Cash Flow" height={320} />)

    expect(capturedProps).not.toBeNull()
    expect(capturedProps?.style).toEqual({ height: "320px", width: "100%" })

    const option = capturedProps?.option ?? {}
    expect(option.title).toEqual({ text: "Cash Flow", left: "center", textStyle: { color: "#64748b" } })
    expect(option.graphic).toEqual({
      type: "text",
      left: "center",
      top: "middle",
      style: {
        text: "Add transaction data to see cash flow visualization",
        fill: "#64748b",
        fontSize: 14,
      },
    })
  })

  it("AC16.21.7 builds sankey nodes and links for inflows and outflows", () => {
    render(
      <SankeyChart
        title="Detailed Cash Flow"
        operating={[
          { category: "operating", subcategory: "Sales", amount: 300 },
          { category: "operating", subcategory: "Payroll", amount: -120 },
          { category: "operating", subcategory: "Invalid", amount: "NaN" },
        ]}
        investing={[{ category: "investing", subcategory: "Equipment", amount: -80 }]}
        financing={[{ category: "financing", subcategory: "Loan", amount: 220 }]}
      />,
    )

    const option = capturedProps?.option as {
      title: { text: string }
      series: Array<{ data: Array<{ name: string }>; links: Array<{ source: string; target: string; value: number }> }>
    }
    expect(option.title.text).toBe("Detailed Cash Flow")

    const series = option.series[0]
    const nodeNames = series.data.map((n) => n.name)
    expect(nodeNames).toContain("Operating")
    expect(nodeNames).toContain("Operating-Inflows")
    expect(nodeNames).toContain("Operating-Outflows")
    expect(nodeNames).toContain("Operating-Sales")
    expect(nodeNames).toContain("Operating-Payroll")
    expect(nodeNames).toContain("Investing-Equipment")
    expect(nodeNames).toContain("Financing-Loan")

    expect(series.links).toEqual(
      expect.arrayContaining([
        { source: "Operating-Inflows", target: "Operating-Sales", value: 300 },
        { source: "Operating-Payroll", target: "Operating-Outflows", value: 120 },
        { source: "Investing-Equipment", target: "Investing-Outflows", value: 80 },
        { source: "Financing-Inflows", target: "Financing-Loan", value: 220 },
      ]),
    )
  })

  it("AC16.21.8 recomputes theme-driven colors on root attribute change", async () => {
    render(
      <SankeyChart
        operating={[{ category: "operating", subcategory: "Sales", amount: 100 }]}
        financing={[{ category: "financing", subcategory: "Loan", amount: -20 }]}
      />,
    )

    const initialOption = capturedProps?.option as {
      series: Array<{ data: Array<{ name: string; itemStyle?: { color: string } }> }>
    }
    const initialNodeColor = initialOption.series[0].data.find((n) => n.name === "Operating")?.itemStyle?.color
    expect(initialNodeColor).toBe("#1f9d55")

    colors["--success"] = "#00ff99"
    colors["--foreground-muted"] = "#334155"
    observerCallback?.([{ attributeName: "class" } as MutationRecord])

    await waitFor(() => {
      const updatedOption = capturedProps?.option as {
        series: Array<{ data: Array<{ name: string; itemStyle?: { color: string } }> }>
      }
      const updatedNodeColor = updatedOption.series[0].data.find((n) => n.name === "Operating")?.itemStyle?.color
      const subcategoryColor = updatedOption.series[0].data.find((n) => n.name === "Operating-Sales")?.itemStyle?.color
      expect(updatedNodeColor).toBe("#00ff99")
      expect(subcategoryColor).toBe("#334155")
    })
  })
})
