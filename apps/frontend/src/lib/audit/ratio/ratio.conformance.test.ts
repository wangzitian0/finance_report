// Frontend side of the cross-language ratio conformance suite (#1167).
//
// Proves the frontend rendering of the ratio standard: AC12.9.1 (value type +
// percent policy). Loads the SAME language-neutral standard the Python reference
// uses (common/audit/ratio/conformance/vectors.json) and asserts the TS impl reproduces
// every value, so the frontend cannot drift from the backend on the HALF_UP
// percent rounding. See common/audit/ratio/conformance/README.md.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

import { FloatNotAllowedError, PERCENT_DP, PERCENT_ROUNDING, Ratio, UndefinedRatioError } from "./index";

const here = dirname(fileURLToPath(import.meta.url));
const vectorsPath = resolve(here, "../../../../../../common/audit/ratio/conformance/vectors.json");
const VECTORS = JSON.parse(readFileSync(vectorsPath, "utf-8")) as {
  percent_dp: number;
  percent_rounding: string;
  to_percent: { ratio: string; dp: number; expected: string }[];
  percent_of: { part: string; whole: string; dp: number; expected: string }[];
  from_percent: { percent: string; expected_percent_2dp: string }[];
};

describe("ratio conformance (cross-language standard #1167)", () => {
  it("declares the same percent policy (2 dp, HALF_UP)", () => {
    expect(VECTORS.percent_dp).toBe(PERCENT_DP);
    expect(VECTORS.percent_rounding).toBe("ROUND_HALF_UP");
    expect(PERCENT_ROUNDING).toBe(Decimal.ROUND_HALF_UP);
  });

  it("matches every to_percent vector (HALF_UP, not HALF_EVEN)", () => {
    for (const c of VECTORS.to_percent) {
      const got = new Ratio(c.ratio).toPercent(c.dp);
      expect(got.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
    }
  });

  it("matches every percent_of (fraction → percent) vector", () => {
    for (const c of VECTORS.percent_of) {
      const got = Ratio.fraction(c.part, c.whole).toPercent(c.dp);
      expect(got.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
    }
  });

  it("round-trips from_percent", () => {
    for (const c of VECTORS.from_percent) {
      const got = Ratio.fromPercent(c.percent).toPercent(2);
      expect(got.equals(new Decimal(c.expected_percent_2dp)), JSON.stringify(c)).toBe(true);
    }
  });
});

describe("ratio value-type laws (TS rendering of the contract)", () => {
  it("rejects float (JS number) values", () => {
    // @ts-expect-error number is intentionally not assignable to RatioInput
    expect(() => new Ratio(0.125)).toThrow(FloatNotAllowedError);
  });

  it("treats a zero whole as undefined", () => {
    expect(() => Ratio.fraction("1", "0")).toThrow(UndefinedRatioError);
  });

  it("supports dimensionless arithmetic + comparison", () => {
    const a = new Ratio("0.1");
    const b = new Ratio("0.2");
    expect(a.add(b).value.equals(new Decimal("0.3"))).toBe(true);
    expect(b.subtract(a).value.equals(new Decimal("0.1"))).toBe(true);
    expect(a.compareTo(b)).toBe(-1);
    expect(a.equals(new Ratio("0.1"))).toBe(true);
    expect(Ratio.zero().value.equals(new Decimal("0"))).toBe(true);
    expect(Ratio.zero().isZero()).toBe(true);
    expect(a.isZero()).toBe(false);
  });

  it("renders percent strings (formatPercent / toString)", () => {
    expect(new Ratio("0.125").formatPercent()).toBe("12.50%");
    expect(String(new Ratio("0.5"))).toBe("50.00%");
  });
});
