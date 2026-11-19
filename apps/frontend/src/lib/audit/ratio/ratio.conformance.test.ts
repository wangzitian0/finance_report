import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Decimal from "decimal.js";
import { expect, it } from "vitest";
import { FloatNotAllowedError, PERCENT_DP, PERCENT_ROUNDING, Ratio, UndefinedRatioError } from "./index";
const V = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../common/audit/ratio/conformance/vectors.json"), "utf-8"));
it("ratio conformance and value-type laws", () => {
  expect([V.percent_dp, V.percent_rounding, PERCENT_ROUNDING]).toEqual([PERCENT_DP, "ROUND_HALF_UP", Decimal.ROUND_HALF_UP]);
  for (const c of V.to_percent) expect(new Ratio(c.ratio).toPercent(c.dp).equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
  for (const c of V.percent_of) expect(Ratio.fraction(c.part, c.whole).toPercent(c.dp).equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
  for (const c of V.from_percent) expect(Ratio.fromPercent(c.percent).toPercent(2).equals(new Decimal(c.expected_percent_2dp)), JSON.stringify(c)).toBe(true);
  // @ts-expect-error number is intentionally not assignable to RatioInput
  expect(() => new Ratio(0.125)).toThrow(FloatNotAllowedError);
  expect(() => Ratio.fraction("1", "0")).toThrow(UndefinedRatioError);
  const a = new Ratio("0.1"), b = new Ratio("0.2");
  expect([a.add(b).value.equals(new Decimal("0.3")), b.subtract(a).value.equals(new Decimal("0.1")), a.compareTo(b), a.equals(new Ratio("0.1")), Ratio.zero().value.equals(new Decimal("0")), Ratio.zero().isZero(), a.isZero()]).toEqual([true, true, -1, true, true, true, false]);
  expect([new Ratio("0.125").formatPercent(), String(new Ratio("0.5"))]).toEqual(["12.50%", "50.00%"]);
});
// AC-audit.9.1
