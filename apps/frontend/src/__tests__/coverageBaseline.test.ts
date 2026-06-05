import { describe, expect, it } from "vitest"

import vitestConfig from "../../vitest.config"

describe("frontend coverage baseline", () => {
  it("AC8.13.92 keeps the frontend Vitest threshold baseline code-owned", () => {
    const thresholds = vitestConfig.test?.coverage?.thresholds

    expect(thresholds).toMatchObject({
      lines: 98,
      statements: 98,
      functions: 98,
      branches: 84,
      autoUpdate: false,
    })
  })
})
