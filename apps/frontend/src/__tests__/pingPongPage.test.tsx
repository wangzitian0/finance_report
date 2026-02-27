import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import PingPongPage from "@/app/ping-pong/page"
import { apiFetch } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

describe("PingPongPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)

  beforeEach(() => {
    mockedApiFetch.mockReset()
  })

  it("AC16.12.8 loads initial state and shows current value", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      state: "ping",
      toggle_count: 0,
      updated_at: "2026-01-01T00:00:00Z",
    })

    render(<PingPongPage />)

    await waitFor(() => expect(screen.getByText("PING")).toBeInTheDocument())
    expect(screen.getByText(/Toggle count:/)).toBeInTheDocument()
  })

  it("AC16.12.9 toggles state and updates count", async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ state: "ping", toggle_count: 0, updated_at: null })
      .mockResolvedValueOnce({ state: "pong", toggle_count: 1, updated_at: "2026-01-01T00:00:01Z" })

    render(<PingPongPage />)

    await waitFor(() => expect(screen.getByText("PING")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Toggle State" }))

    await waitFor(() => expect(screen.getByText("PONG")).toBeInTheDocument())
    expect(screen.getByText("1")).toBeInTheDocument()
  })

  it("AC16.12.10 renders retry flow on initial error", async () => {
    mockedApiFetch
      .mockRejectedValueOnce(new Error("network failed"))
      .mockResolvedValueOnce({ state: "ping", toggle_count: 0, updated_at: null })

    render(<PingPongPage />)

    await waitFor(() => expect(screen.getByText("network failed")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))

    await waitFor(() => expect(screen.getByText("PING")).toBeInTheDocument())
  })
})
