import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import LoginPage from "@/app/login/page"
import { apiFetch } from "@/lib/api"
import { setUser } from "@/lib/auth"

const pushMock = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  setUser: vi.fn(),
}))

describe("LoginPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)
  const mockedSetUser = vi.mocked(setUser)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    mockedSetUser.mockReset()
    pushMock.mockReset()
  })

  it("AC16.12.5 submits login payload and redirects", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      id: "u1",
      email: "user@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
      access_token: "token-1",
    })

    render(<LoginPage />)

    fireEvent.change(screen.getByLabelText("Email Address"), {
      target: { value: "user@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({ method: "POST" }),
      )
    })
    expect(mockedSetUser).toHaveBeenCalledWith("u1", "user@example.com", "token-1")
    expect(pushMock).toHaveBeenCalledWith("/dashboard")
  })

  it("AC16.12.6 switches to register mode and uses register endpoint", async () => {
    mockedApiFetch.mockResolvedValueOnce({
      id: "u2",
      email: "new@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
      access_token: "token-2",
    })

    render(<LoginPage />)

    fireEvent.click(screen.getAllByRole("button", { name: "Register" })[0])
    fireEvent.change(screen.getByLabelText("Email Address"), {
      target: { value: "new@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({ method: "POST" }),
      )
    })
  })

  it("AC16.12.7 shows API error and exits loading state", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("invalid credentials"))

    render(<LoginPage />)

    fireEvent.change(screen.getByLabelText("Email Address"), {
      target: { value: "bad@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))

    await waitFor(() => expect(screen.getByText("invalid credentials")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument()
  })
})
