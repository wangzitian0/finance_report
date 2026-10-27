import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AiSettingsPanel, changedChoices } from "@/components/settings/SettingsPanels"
import { apiOperation } from "@/lib/api-client"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

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
    if (op === "get_current_user_settings_users_me_settings_get") {
      return { enable_ai_reconciliation: true, enable_ai_classification: false, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: false } as any
    }
    return {} as any
  })
})

describe("AiSettingsPanel (EPIC-022 AC22.4.3, AC22.15.2)", () => {
  // AC-reconciliation.fe-ia-reconciliation.1
  it("AC22.4.3 links to the AI suggestion review surface so it is not orphaned", async () => {
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())
    expect(screen.getByRole("link", { name: /Review AI suggestions/i })).toHaveAttribute(
      "href",
      "/audit?tab=needs-you#ai-suggestions",
    )
  })

  // AC-llm.fe-ia-ai-settings.1
  it("AC22.15.2 renders the loaded flags and keeps Save disabled until edited", async () => {
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    expect(screen.getByLabelText("Enable AI reconciliation")).toBeChecked()
    expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked()
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC22.15.2 submits edited flags via patchUserSettings and shows success", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return { enable_ai_reconciliation: true, enable_ai_classification: false, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: false } as any
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        return { enable_ai_reconciliation: true, enable_ai_classification: true, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: true } as any
      }
      return {} as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    const save = screen.getByRole("button", { name: /Save changes/i })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("patch_current_user_settings_users_me_settings_patch", {
        body: { enable_ai_classification: true },
      }),
    )
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("AI settings saved", "success"))
    // After a successful save the form is no longer dirty.
    await waitFor(() => expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled())
  })

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — turns the automatic acceptance off and sends only that change", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return { enable_ai_reconciliation: false, enable_ai_classification: true, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: true } as any
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        return { enable_ai_reconciliation: false, enable_ai_classification: true, auto_accept_ai_suggestions: false, auto_accept_ai_suggestions_active: false } as any
      }
      return {} as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeChecked()
    fireEvent.click(screen.getByLabelText("Auto-accept AI suggestions"))
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("patch_current_user_settings_users_me_settings_patch", {
        body: { auto_accept_ai_suggestions: false },
      }),
    )
  })

  it("AC-extraction.auto-accept.1 — the switch is off and locked while AI classification is off", async () => {
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    // The mock loads enable_ai_classification = false and auto_accept_ai_suggestions = true.
    expect(screen.getByLabelText("Auto-accept AI suggestions")).not.toBeChecked()
    expect(screen.getByLabelText("Auto-accept AI suggestions")).toBeDisabled()
  })

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — a save of another switch stores no choice about the automatic acceptance", async () => {
    // The user turned AI classification off earlier. The system does not accept anything, but the user never
    // chose to turn the automatic acceptance off. A save of another switch must not store a value for it.
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: false,
          enable_ai_classification: false,
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: false,
        } as any
      }
      return {
        enable_ai_reconciliation: true,
        enable_ai_classification: false,
        auto_accept_ai_suggestions: true,
        auto_accept_ai_suggestions_active: false,
      } as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI reconciliation"))
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith("patch_current_user_settings_users_me_settings_patch", {
        body: { enable_ai_reconciliation: true },
      }),
    )
  })

  // AC-extraction.auto-accept.1
  it.each([
    ["the operator turned it off", true, true, false, true],
    ["the user turned it off", true, false, false, false],
    ["AI classification is off", false, true, false, false],
    ["everything is on", true, true, true, false],
  ])("AC-extraction.auto-accept.1 — the operator note when %s: %s", async (_label, classification, choice, active, noteShown) => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: false,
          enable_ai_classification: classification,
          auto_accept_ai_suggestions: choice,
          auto_accept_ai_suggestions_active: active,
        } as any
      }
      return {} as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    const note = screen.queryByRole("note")
    if (noteShown) {
      expect(note).toHaveTextContent("turned the automatic acceptance off for all accounts")
    } else {
      expect(note).toBeNull()
    }
  })

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — an unsaved edit of AI classification does not show the operator note", async () => {
    // The saved state has AI classification off, so the automatic acceptance is not in use. The cause is the
    // user, not the operator. Turning AI classification on in the form must not blame the operator.
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return {
          enable_ai_reconciliation: false,
          enable_ai_classification: false,
          auto_accept_ai_suggestions: true,
          auto_accept_ai_suggestions_active: false,
        } as any
      }
      return {} as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))

    expect(screen.getByLabelText("Enable AI classification")).toBeChecked()
    expect(screen.queryByRole("note")).toBeNull()
  })

  it("AC22.15.2 surfaces an error and keeps the draft when the PATCH fails", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "get_current_user_settings_users_me_settings_get") {
        return { enable_ai_reconciliation: true, enable_ai_classification: false, auto_accept_ai_suggestions: true, auto_accept_ai_suggestions_active: false } as any
      }
      if (op === "patch_current_user_settings_users_me_settings_patch") {
        throw new Error("Save failed")
      }
      return {} as any
    })
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Save failed"))
    // Edit is preserved so the user can retry.
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked()
    expect(showToast).not.toHaveBeenCalled()
  })

  it("AC22.15.2 Reset reverts the draft to the last saved values", async () => {
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText("Enable AI classification"))
    expect(screen.getByLabelText("Enable AI classification")).toBeChecked()

    fireEvent.click(screen.getByRole("button", { name: /Reset/i }))
    expect(screen.getByLabelText("Enable AI classification")).not.toBeChecked()
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled()
  })

  it("AC22.15.2 shows a load error when fetchUserSettings rejects", async () => {
    mockedApiOperation.mockReset()
    mockedApiOperation.mockRejectedValue(new Error("Load failed"))
    render(<AiSettingsPanel />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Load failed"))
  })
})

describe("changedChoices (AC-extraction.auto-accept.1)", () => {
  const saved = {
    enable_ai_reconciliation: false,
    enable_ai_classification: true,
    auto_accept_ai_suggestions: true,
    auto_accept_ai_suggestions_active: true,
  }

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — returns only the choices that differ from the saved value", () => {
    expect(changedChoices(saved, { ...saved, auto_accept_ai_suggestions: false })).toEqual({
      auto_accept_ai_suggestions: false,
    })
    expect(changedChoices(saved, { ...saved, enable_ai_reconciliation: true, enable_ai_classification: false })).toEqual({
      enable_ai_reconciliation: true,
      enable_ai_classification: false,
    })
  })

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — returns nothing when no choice changed, and never the read-only value", () => {
    expect(changedChoices(saved, { ...saved })).toEqual({})
    expect(changedChoices(saved, { ...saved, auto_accept_ai_suggestions_active: false })).toEqual({})
  })

  // AC-extraction.auto-accept.1
  it("AC-extraction.auto-accept.1 — sends all three choices when no saved value exists", () => {
    expect(changedChoices(null, saved)).toEqual({
      enable_ai_reconciliation: false,
      enable_ai_classification: true,
      auto_accept_ai_suggestions: true,
    })
  })
})
