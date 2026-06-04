import { describe, expect, it } from "vitest"

import { GET } from "@/app/frontend-version.json/route"

describe("frontend version route", () => {
  it("AC8.13.90 returns deployed frontend version metadata for PR preview readiness", async () => {
    const previousSha = process.env.GIT_COMMIT_SHA
    process.env.GIT_COMMIT_SHA = "test-sha-123"

    try {
      const response = GET()

      expect(response.status).toBe(200)
      expect(response.headers.get("Cache-Control")).toBe("no-store")
      await expect(response.json()).resolves.toEqual({
        git_sha: "test-sha-123",
        version: "test-sha-123",
      })
    } finally {
      if (previousSha === undefined) {
        delete process.env.GIT_COMMIT_SHA
      } else {
        process.env.GIT_COMMIT_SHA = previousSha
      }
    }
  })
})
