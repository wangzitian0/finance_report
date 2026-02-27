import { describe, expect, it } from "vitest"

import { DELETE, GET, PATCH, POST, PUT } from "@/app/api/[...path]/route"

describe("API catch-all route", () => {
  it("AC16.17.7 returns 503 JSON for all supported methods", async () => {
    const responses = await Promise.all([GET(), POST(), PUT(), PATCH(), DELETE()])

    for (const response of responses) {
      expect(response.status).toBe(503)
      await expect(response.json()).resolves.toEqual({
        detail: "API service temporarily unavailable. Please try again in a moment.",
        code: "SERVICE_UNAVAILABLE",
      })
    }
  })
})
