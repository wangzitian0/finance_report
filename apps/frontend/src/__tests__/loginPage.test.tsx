import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import LoginPage from "@/app/login/page"
import { apiFetch } from "@/lib/api"
import { setUser } from "@/lib/auth"
import { track, ANALYTICS_EVENTS } from "@/lib/analytics"

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

vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
}))

describe("LoginPage", () => {
  const mockedApiFetch = vi.mocked(apiFetch)
  const mockedSetUser = vi.mocked(setUser)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    mockedSetUser.mockReset()
    pushMock.mockReset()
    vi.mocked(track).mockReset()
  })

  it("AC16.12.5 AC22.1.3 submits login payload and redirects to Home", async () => {
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
    expect(pushMock).toHaveBeenCalledWith("/")
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

    fireEvent.click(screen.getByTestId("auth-mode-toggle-register"))
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

  it("AC8.19.1 login register controls expose distinct test ids and accessible names", () => {
    render(<LoginPage />)

    const toggleRegister = screen.getByTestId("auth-mode-toggle-register")
    const ctaRegister = screen.getByTestId("login-register-cta")

    // Distinct, stable hooks for the two register controls.
    expect(toggleRegister).not.toBe(ctaRegister)

    // Visible copy is preserved for users (no copy regression, AC requirement 3).
    expect(toggleRegister).toHaveTextContent("Register")
    expect(ctaRegister).toHaveTextContent("Register")

    // Accessible names are disambiguated so no two buttons share the same name.
    expect(toggleRegister).toHaveAccessibleName("Switch to register")
    expect(ctaRegister).toHaveAccessibleName("Register a new account")

    // The previously ambiguous strict accessible name "Register" now matches no button.
    expect(screen.queryAllByRole("button", { name: "Register" })).toHaveLength(0)
  })

  it("AC22.18.3 tracks SIGNUP only on successful register, not on login", async () => {
    // Successful register: the signup funnel event fires.
    mockedApiFetch.mockResolvedValueOnce({
      id: "u3",
      email: "signup@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
      access_token: "token-3",
    })

    const { unmount } = render(<LoginPage />)

    fireEvent.click(screen.getByTestId("auth-mode-toggle-register"))
    fireEvent.change(screen.getByLabelText("Email Address"), {
      target: { value: "signup@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }))

    await waitFor(() => {
      expect(vi.mocked(track)).toHaveBeenCalledWith(ANALYTICS_EVENTS.SIGNUP)
    })

    unmount()
    vi.mocked(track).mockReset()

    // Plain login must NOT be counted as a signup.
    mockedApiFetch.mockResolvedValueOnce({
      id: "u4",
      email: "login@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
      access_token: "token-4",
    })

    render(<LoginPage />)

    fireEvent.change(screen.getByLabelText("Email Address"), {
      target: { value: "login@example.com" },
    })
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/")
    })
    expect(vi.mocked(track)).not.toHaveBeenCalledWith(ANALYTICS_EVENTS.SIGNUP)
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

  it("AC16.12.13 toggles password visibility", () => {
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

  it("AC16.12.14 shows error with alert role and aria-live", async () => {
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

  it("AC16.12.15 shows mode toggle links", () => {
    render(<LoginPage />)
    const toggleParagraph = screen.getByText("Don't have an account?").closest("p")!
    const registerLink = toggleParagraph.querySelector("button")!
    fireEvent.click(registerLink)
    const toggleParagraph2 = screen.getByText("Already have an account?").closest("p")!
    const signInLink = toggleParagraph2.querySelector("button")!
    fireEvent.click(signInLink)
    expect(screen.getByText("Don't have an account?")).toBeInTheDocument()
  })

  it("AC16.12.16 shows loading spinner during submission", async () => {
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
