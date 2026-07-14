import { describe, expect, it } from "vitest"

import vitestConfig from "../../vitest.config"

interface CoverageConfigWithThresholds {
  thresholds?: Record<string, unknown>
}

describe("frontend coverage baseline", () => {
  // AC-testing.fe-coverage.4
  it("AC8.13.92 keeps the frontend Vitest threshold baseline code-owned", () => {
    const coverage = vitestConfig.test?.coverage as CoverageConfigWithThresholds | undefined
    const thresholds = coverage?.thresholds

    expect(thresholds).toMatchObject({
      lines: 98,
      statements: 98,
      functions: 98,
      branches: 84,
      autoUpdate: false,
    })
  })
})
