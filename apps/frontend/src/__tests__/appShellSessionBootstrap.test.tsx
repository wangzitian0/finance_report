import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useSessionBootstrap } from "@/hooks/useSessionBootstrap"
import { apiOperation } from "@/lib/api-client"
import { clearUser, getUserEmail, getUserId, setUser } from "@/lib/auth"

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}))

const mockedApiOperation = vi.mocked(apiOperation)

beforeEach(() => {
  localStorage.clear()
  mockedApiOperation.mockReset()
})

describe("useSessionBootstrap (EPIC-022 AC22.15.3 / #1010)", () => {
  // AC-identity.fe-ia-identity.1
  it("AC22.15.3 does not call /auth/me when there is no local session", async () => {
    renderHook(() => useSessionBootstrap())
    expect(mockedApiOperation).not.toHaveBeenCalled()
  })

  it("AC22.15.3 consumes /auth/me on mount and refreshes the cached identity", async () => {
    setUser("stale-id", "stale@example.com")
    mockedApiOperation.mockResolvedValue({
      id: "fresh-id",
      email: "fresh@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
    } as any)

    renderHook(() => useSessionBootstrap())

    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("get_me_auth_me_get"))
    await waitFor(() => expect(getUserId()).toBe("fresh-id"))
    expect(getUserEmail()).toBe("fresh@example.com")
  })

  it("AC22.15.3 clears the stale local identity when /auth/me fails", async () => {
    setUser("stale-id", "stale@example.com")
    mockedApiOperation.mockRejectedValue(new Error("boom"))

    renderHook(() => useSessionBootstrap())

    await waitFor(() => expect(getUserId()).toBeNull())
  })

  it("AC22.15.3 is a no-op after the session was cleared", () => {
    setUser("id", "e@example.com")
    clearUser()
    renderHook(() => useSessionBootstrap())
    expect(mockedApiOperation).not.toHaveBeenCalled()
  })
})
