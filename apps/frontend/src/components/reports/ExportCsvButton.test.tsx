import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ExportCsvButton } from "./ExportCsvButton"
import { apiDownload } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiDownload: vi.fn(),
}))

describe("ExportCsvButton", () => {
  const mockedApiDownload = vi.mocked(apiDownload)

  beforeEach(() => {
    mockedApiDownload.mockReset()
  })

  it("AC5.17.1 surfaces authenticated CSV export failures", async () => {
    mockedApiDownload.mockRejectedValue(new Error("export denied"))

    render(<ExportCsvButton path="/api/reports/export?report_type=cash-flow" />)

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }))

    await waitFor(() =>
      expect(mockedApiDownload).toHaveBeenCalledWith("/api/reports/export?report_type=cash-flow"),
    )
    expect(await screen.findByText("export denied")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled()
  })
})
