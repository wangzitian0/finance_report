import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useSessionBootstrap } from "@/hooks/useSessionBootstrap"
import { fetchCurrentUser } from "@/lib/api"
import { clearUser, getUserEmail, getUserId, setUser } from "@/lib/auth"

vi.mock("@/lib/api", () => ({
  fetchCurrentUser: vi.fn(),
}))

const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser)

beforeEach(() => {
  localStorage.clear()
  mockedFetchCurrentUser.mockReset()
})

describe("useSessionBootstrap (EPIC-022 AC22.15.3 / #1010)", () => {
  it("AC22.15.3 does not call /auth/me when there is no local session", async () => {
    renderHook(() => useSessionBootstrap())
    expect(mockedFetchCurrentUser).not.toHaveBeenCalled()
  })

  it("AC22.15.3 consumes /auth/me on mount and refreshes the cached identity", async () => {
    setUser("stale-id", "stale@example.com")
    mockedFetchCurrentUser.mockResolvedValue({
      id: "fresh-id",
      email: "fresh@example.com",
      name: null,
      created_at: "2026-01-01T00:00:00Z",
    })

    renderHook(() => useSessionBootstrap())

    await waitFor(() => expect(mockedFetchCurrentUser).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getUserId()).toBe("fresh-id"))
    expect(getUserEmail()).toBe("fresh@example.com")
  })

  it("AC22.15.3 clears the stale local identity when /auth/me fails", async () => {
    setUser("stale-id", "stale@example.com")
    mockedFetchCurrentUser.mockRejectedValue(new Error("boom"))

    renderHook(() => useSessionBootstrap())

    await waitFor(() => expect(getUserId()).toBeNull())
  })

  it("AC22.15.3 is a no-op after the session was cleared", () => {
    setUser("id", "e@example.com")
    clearUser()
    renderHook(() => useSessionBootstrap())
    expect(mockedFetchCurrentUser).not.toHaveBeenCalled()
  })
})
