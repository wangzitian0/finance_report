import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import GeneralSettingsPage from "@/components/settings/GeneralSettingsPanel"
import { apiOperation } from "@/lib/api-client"

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const showToast = vi.fn()
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast }),
}))

const mockedApiOperation = vi.mocked(apiOperation)

beforeEach(() => {
  showToast.mockReset()
  mockedApiOperation.mockReset()
  mockedApiOperation.mockImplementation(async (op: any) => {
    if (op === "get_base_currency_app_config_base_currency_get") {
      return { base_currency: "SGD" } as any
    }
    return {} as any
  })
})

describe("GeneralSettingsPage (EPIC-012 AC12.39.3)", () => {
  // AC-pricing.fe-settings.1
  it("AC12.39.3 renders the effective base currency and keeps Save disabled until edited", async () => {
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD")
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC12.39.3 submits the edited currency via updateBaseCurrency and shows success", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_base_currency_app_config_base_currency_get") {
        return { base_currency: "SGD" } as any
      }
      if (op === "update_base_currency_app_config_base_currency_put") {
        return { base_currency: "EUR" } as any
      }
      return {} as any
    })
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "eur" } })
    const save = screen.getByRole("button", { name: /Save changes/i })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("update_base_currency_app_config_base_currency_put", {
        body: { base_currency: "EUR" },
      })
    )
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Base currency saved", "success"))
    await waitFor(() => expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled())
  })

  it("AC12.39.3 surfaces an error and keeps the draft when the update fails", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_base_currency_app_config_base_currency_get") {
        return { base_currency: "SGD" } as any
      }
      if (op === "update_base_currency_app_config_base_currency_put") {
        throw new Error("not an ISO-4217 currency code")
      }
      return {} as any
    })
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "XYZ" } })
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not an ISO-4217 currency code"))
    expect(screen.getByLabelText("Base currency")).toHaveValue("XYZ")
    expect(showToast).not.toHaveBeenCalled()
  })

  it("AC12.39.3 surfaces a load error when fetching the base currency fails", async () => {
    mockedApiOperation.mockReset()
    mockedApiOperation.mockRejectedValueOnce(new Error("Network Error"))
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Network Error"))
  })

  it("AC12.39.3 Reset restores the saved value and clears the dirty state", async () => {
    render(<GeneralSettingsPage />)
    await waitFor(() => expect(screen.getByText("General Settings")).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "usd" } })
    expect(screen.getByLabelText("Base currency")).toHaveValue("USD")
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /Reset/i }))
    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD")
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument()
    expect(mockedApiOperation).not.toHaveBeenCalledWith("update_base_currency_app_config_base_currency_put", expect.anything())
  })
})
