import { describe, expect, it, vi } from "vitest"

import Home from "@/app/page"

const redirectMock = vi.fn()

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
}))

describe("Root page", () => {
  it("AC16.16.1 redirects to dashboard", () => {
    Home()
    expect(redirectMock).toHaveBeenCalledWith("/dashboard")
  })
})
