import { render, screen, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import {
  REQUIRED_REPORT_SOURCE_CLASSES,
  SourceIntakeChecklist,
} from "@/components/source-intake/SourceIntakeChecklist"

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

describe("SourceIntakeChecklist", () => {
  it("AC19.15.1 renders every required source class with intake links", () => {
    render(<SourceIntakeChecklist />)

    expect(REQUIRED_REPORT_SOURCE_CLASSES).toEqual([
      "bank_statement",
      "brokerage_statement",
      "settlement_note",
      "esop_rsu_plan",
      "property_statement",
      "liability_statement",
      "csv_export",
      "manual_record",
    ])

    const checklist = screen.getByRole("region", { name: "Report source intake checklist" })
    for (const label of [
      "Bank statements",
      "Brokerage statements",
      "Settlement notes",
      "ESOP / RSU plans",
      "Property statements",
      "Liability statements",
      "CSV exports",
      "Manual records",
    ]) {
      expect(within(checklist).getByText(label)).toBeInTheDocument()
    }

    expect(screen.getByRole("link", { name: "Upload bank statements" })).toHaveAttribute("href", "/upload")
    expect(screen.getByRole("link", { name: "Upload brokerage statements" })).toHaveAttribute("href", "/upload")
    expect(screen.getByRole("link", { name: "Capture settlement notes" })).toHaveAttribute("href", "/upload")
    expect(screen.getByRole("link", { name: "Add ESOP / RSU plans" })).toHaveAttribute(
      "href",
      "/portfolio/evidence?source_class=esop_rsu_plan",
    )
    expect(screen.getByRole("link", { name: "Add property statements" })).toHaveAttribute(
      "href",
      "/portfolio/evidence?source_class=property_statement",
    )
    expect(screen.getByRole("link", { name: "Add liability statements" })).toHaveAttribute(
      "href",
      "/portfolio/evidence?source_class=liability_statement",
    )
    expect(screen.getByRole("link", { name: "Upload CSV exports" })).toHaveAttribute("href", "/upload")
    expect(screen.getByRole("link", { name: "Enter manual records" })).toHaveAttribute("href", "/journal")
  })

  it("AC19.15.2 labels readiness gaps and manual-trusted source classes", () => {
    render(
      <SourceIntakeChecklist
        sourceTrustSummary={{
          source_classes: ["bank_statement", "property_statement", "manual_record"],
          deterministic_pr_source_classes: ["bank_statement", "property_statement", "manual_record"],
          post_merge_llm_ocr_source_classes: ["bank_statement"],
          manual_trusted_source_classes: ["property_statement", "manual_record"],
          gap_source_classes: ["manual_record"],
          blocker_codes: ["missing_source_coverage"],
        }}
      />,
    )

    expect(within(screen.getByTestId("source-intake-bank_statement")).getByText("Import supported")).toBeInTheDocument()
    expect(within(screen.getByTestId("source-intake-property_statement")).getByText("Manual-trusted")).toBeInTheDocument()
    expect(within(screen.getByTestId("source-intake-manual_record")).getByText("Needs source")).toBeInTheDocument()
    expect(screen.queryByText("Automatically imported manual evidence")).not.toBeInTheDocument()
  })

  it("AC19.15.2 distinguishes deterministic proof from sources outside the current summary", () => {
    render(
      <SourceIntakeChecklist
        sourceTrustSummary={{
          source_classes: ["csv_export"],
          deterministic_pr_source_classes: ["csv_export"],
          post_merge_llm_ocr_source_classes: [],
          manual_trusted_source_classes: [],
          gap_source_classes: [],
          blocker_codes: [],
        }}
      />,
    )

    expect(within(screen.getByTestId("source-intake-csv_export")).getByText("Deterministic proof")).toBeInTheDocument()
    expect(within(screen.getByTestId("source-intake-bank_statement")).getByText("Planned source")).toBeInTheDocument()
  })
})
