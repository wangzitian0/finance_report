import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import GeneralSettingsPage from "@/app/(main)/settings/general/page"
import { fetchBaseCurrency, updateBaseCurrency } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  fetchBaseCurrency: vi.fn(),
  updateBaseCurrency: vi.fn(),
}))

const showToast = vi.fn()
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast }),
}))

const mockedFetch = vi.mocked(fetchBaseCurrency)
const mockedUpdate = vi.mocked(updateBaseCurrency)

beforeEach(() => {
  showToast.mockReset()
  mockedFetch.mockReset()
  mockedUpdate.mockReset()
  mockedFetch.mockResolvedValue({ base_currency: "SGD" })
})

describe("GeneralSettingsPage (EPIC-012 AC12.39.3)", () => {
  it("AC12.39.3 renders the effective base currency and keeps Save disabled until edited", async () => {
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD")
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC12.39.3 submits the edited currency via updateBaseCurrency and shows success", async () => {
    mockedUpdate.mockResolvedValue({ base_currency: "EUR" })
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "eur" } })
    const save = screen.getByRole("button", { name: /Save changes/i })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith("EUR"))
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Base currency saved", "success"))
    await waitFor(() => expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled())
  })

  it("AC12.39.3 surfaces an error and keeps the draft when the update fails", async () => {
    mockedUpdate.mockRejectedValue(new Error("not an ISO-4217 currency code"))
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "XYZ" } })
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not an ISO-4217 currency code"))
    expect(screen.getByLabelText("Base currency")).toHaveValue("XYZ")
    expect(showToast).not.toHaveBeenCalled()
  })
})
