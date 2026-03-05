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
    expect(mockedSetUser).toHaveBeenCalledTimes(1)
    expect(mockedSetUser).toHaveBeenCalledWith("u1", "user@example.com", "token-1")
    expect(pushMock).toHaveBeenCalledTimes(1)
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
    expect(mockedSetUser).not.toHaveBeenCalled()
    expect(pushMock).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument()
  })

  it("AC16.12.8 toggles password visibility", () => {
    render(<LoginPage />)

    const passwordInput = screen.getByLabelText("Password") as HTMLInputElement
    expect(passwordInput.type).toBe("password")

    const toggleButton = screen.getByRole("button", { name: "Show password" })
    fireEvent.click(toggleButton)

    expect(passwordInput.type).toBe("text")
    expect(screen.getByRole("button", { name: "Hide password" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }))
    expect(passwordInput.type).toBe("password")
  })

  it("AC16.12.9 shows error with alert role and aria-live", async () => {
    mockedApiFetch.mockRejectedValueOnce(new Error("bad request"))
    render(<LoginPage />)

    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "a@b.com" } })
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "12345678" } })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))

    await waitFor(() => {
      const alert = screen.getByRole("alert")
      expect(alert).toHaveAttribute("aria-live", "assertive")
      expect(alert).toHaveTextContent("bad request")
    })
  })

  it("AC16.12.10 shows mode toggle links", () => {
    render(<LoginPage />)
    const toggleParagraph = screen.getByText("Don't have an account?").closest("p")!
    const registerLink = toggleParagraph.querySelector("button")!
    fireEvent.click(registerLink)
    const toggleParagraph2 = screen.getByText("Already have an account?").closest("p")!
    const signInLink = toggleParagraph2.querySelector("button")!
    fireEvent.click(signInLink)
    expect(screen.getByText("Don't have an account?")).toBeInTheDocument()
  })

  it("AC16.12.11 shows loading spinner during submission", async () => {
    let resolvePromise: (v: unknown) => void
    mockedApiFetch.mockReturnValueOnce(new Promise((r) => { resolvePromise = r }))

    render(<LoginPage />)
    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "a@b.com" } })
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "12345678" } })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))

    await waitFor(() => expect(screen.getByText("Processing...")).toBeInTheDocument())

    resolvePromise!({ id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01T00:00:00Z", access_token: "tok" })
    await waitFor(() => expect(screen.queryByText("Processing...")).not.toBeInTheDocument())
  })
})
