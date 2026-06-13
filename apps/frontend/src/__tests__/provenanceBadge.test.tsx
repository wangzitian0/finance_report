import "@testing-library/jest-dom/vitest"
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge"

describe("ProvenanceBadge", () => {
  it("AC22.13.2 renders normalized Imported, Manual, and Derived badges", () => {
    render(
      <div>
        <ProvenanceBadge provenance="imported" />
        <ProvenanceBadge provenance="manual" />
        <ProvenanceBadge provenance="derived" />
        <ProvenanceBadge provenance={null} />
      </div>,
    )

    expect(screen.getByText("Imported")).toHaveAccessibleName("Provenance: Imported")
    expect(screen.getByText("Manual")).toHaveAccessibleName("Provenance: Manual")
    expect(screen.getByText("Derived")).toHaveAccessibleName("Provenance: Derived")
    expect(screen.queryByText("Unknown")).not.toBeInTheDocument()

    expect(screen.getByText("Imported")).toHaveClass("badge-success")
    expect(screen.getByText("Manual")).toHaveClass("badge-warning")
    expect(screen.getByText("Derived")).toHaveClass("badge-muted")
    expect(screen.getByText("Manual").className).not.toBe(screen.getByText("Imported").className)
  })
})
