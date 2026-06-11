import { render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AiSettingsPage from "@/app/(main)/settings/ai/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }))

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  mockedApiFetch.mockReset()
  mockedApiFetch.mockResolvedValue({ enable_ai_reconciliation: true, enable_ai_classification: true })
})

describe("AiSettingsPage (EPIC-022 AC22.4.3)", () => {
  it("AC22.4.3 links to the AI suggestion review surface so it is not orphaned", async () => {
    render(<AiSettingsPage />)
    await waitFor(() => expect(screen.getByText("AI Settings")).toBeInTheDocument())
    expect(screen.getByRole("link", { name: /Review AI suggestions/i })).toHaveAttribute(
      "href",
      "/review/ai-suggestions",
    )
  })
})
