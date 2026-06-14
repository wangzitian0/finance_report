import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AiSettingsPage from "@/app/(main)/settings/ai/page"
import { fetchUserSettings, patchUserSettings } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/lib/api", () => ({
  fetchUserSettings: vi.fn(),
  patchUserSettings: vi.fn(),
}))

const showToast = vi.fn()
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast }),
}))

const mockedFetch = vi.mocked(fetchUserSettings)
const mockedPatch = vi.mocked(patchUserSettings)

beforeEach(() => {
  showToast.mockReset()
  mockedFetch.mockReset()
  mockedPatch.mockReset()
  mockedFetch.mockResolvedValue({ enable_ai_reconciliation: true, enable_ai_classification: false })
})

describe("AiSettingsPage (EPIC-022 AC22.4.3, AC22.15.2)", () => {
  it("AC22.4.3 links to the AI suggestion review surface so it is not orphaned", async () => {
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())
    expect(screen.getByRole("link", { name: /Review AI suggestions/i })).toHaveAttribute(
      "href",
      "/review/ai-suggestions",
    )
  })

  it("AC22.15.2 renders the loaded flags and keeps Save disabled until edited", async () => {
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    expect(screen.getByLabelText("Enable AI reconciliation")).toBeChecked()
    expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked()
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC22.15.2 submits edited flags via patchUserSettings and shows success", async () => {
    mockedPatch.mockResolvedValue({ enable_ai_reconciliation: true, enable_ai_classification: true })
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    const save = screen.getByRole("button", { name: /Save changes/i })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith({
        enable_ai_reconciliation: true,
        enable_ai_classification: true,
      }),
    )
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("AI settings saved", "success"))
    // After a successful save the form is no longer dirty.
    await waitFor(() => expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled())
  })

  it("AC22.15.2 surfaces an error and keeps the draft when the PATCH fails", async () => {
    mockedPatch.mockRejectedValue(new Error("Save failed"))
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Save failed"))
    // Edit is preserved so the user can retry.
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked()
    expect(showToast).not.toHaveBeenCalled()
  })

  it("AC22.15.2 Reset reverts the draft to the last saved values", async () => {
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked()

    fireEvent.click(screen.getByRole("button", { name: /Reset/i }))
    expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked()
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC22.15.2 shows a load error when fetchUserSettings rejects", async () => {
    mockedFetch.mockRejectedValue(new Error("Load failed"))
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Load failed"))
  })
})
