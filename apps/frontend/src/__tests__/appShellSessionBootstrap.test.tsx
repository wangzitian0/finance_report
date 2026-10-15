import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useSessionBootstrap } from "@/hooks/useSessionBootstrap"
import { ApiError, apiOperation } from "@/lib/api-client"
import { clearUser, getUserEmail, getUserId, setUser } from "@/lib/auth"

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  return { ApiError: actual.ApiError, apiOperation: vi.fn() }
})

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

  it("AC22.15.3 clears the stale local identity when /auth/me rejects it", async () => {
    setUser("stale-id", "stale@example.com")
    mockedApiOperation.mockRejectedValue(new ApiError("User not found", 404))

    renderHook(() => useSessionBootstrap())

    await waitFor(() => expect(getUserId()).toBeNull())
  })

  it("AC-identity.2478.1 keeps the local identity when /auth/me is aborted or the network fails", async () => {
    setUser("kept-id", "kept@example.com")
    let rejectCall: (err: unknown) => void = () => {}
    const settled = new Promise<void>((resolve) => {
      mockedApiOperation.mockImplementation(
        () =>
          new Promise((_resolve, reject) => {
            rejectCall = (err) => {
              reject(err)
              resolve()
            }
          }) as never,
      )
    })

    renderHook(() => useSessionBootstrap())
    await waitFor(() => expect(mockedApiOperation).toHaveBeenCalledWith("get_me_auth_me_get"))
    rejectCall(new TypeError("Failed to fetch"))
    await settled
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(getUserId()).toBe("kept-id")
    expect(getUserEmail()).toBe("kept@example.com")
  })

  it("AC22.15.3 is a no-op after the session was cleared", () => {
    setUser("id", "e@example.com")
    clearUser()
    renderHook(() => useSessionBootstrap())
    expect(mockedApiOperation).not.toHaveBeenCalled()
  })
})
