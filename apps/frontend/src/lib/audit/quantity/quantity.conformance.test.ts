import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Decimal from "decimal.js";
import { expect, it } from "vitest";
import { FloatNotAllowedError, InvalidUnitError, QUANTITY_DP, QUANTITY_QUANTUM, QUANTITY_ROUNDING, Quantity, Unit, UnitMismatchError, formatQuantity } from "./index";
const V = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../common/audit/quantity/conformance/vectors.json"), "utf-8"));
const D = (v: string) => new Decimal(v), Q = (v: string, u = "shares") => new Quantity(v, u), E = expect;
it("AC-audit.30.1 AC-audit.30.2 AC-audit.30.4 quantity", () => {
E([QUANTITY_DP, QUANTITY_QUANTUM.equals(D(V.quantity_quantum)), QUANTITY_ROUNDING, V.default_rounding]).toEqual([V.quantity_dp, true, Decimal.ROUND_HALF_UP, "ROUND_HALF_UP"]);
for (const c of V.quantize) E(Q(c.value, c.unit).quantize().value.equals(D(c.expected))).toBe(true);
for (const c of V.unit_normalize) E(new Unit(c.input).code).toBe(c.expected);
for (const bad of V.unit_invalid) E(() => new Unit(bad)).toThrow(InvalidUnitError);
const u = new Unit("shares");
E([Unit.of(u) === u, Unit.of("SHARES").equals(u), String(u)]).toEqual([true, true, "shares"]);
for (const c of V.ratio) E(Q(c.part, c.unit).ratioTo(Q(c.whole, c.unit)).toPercent().equals(D(c.expected_percent_2dp))).toBe(true);
// @ts-expect-error number rejected
E(() => new Quantity(0.125, "shares")).toThrow(FloatNotAllowedError);
E(() => Q("Infinity")).toThrow(FloatNotAllowedError);
const a = Q("1.25"), b = Q("2.75");
E(new Quantity(D("1.2345675"), "shares").quantize(Decimal.ROUND_HALF_DOWN).value.equals(D("1.234567"))).toBe(true);
E([a.add(b).equals(Q("4")), b.subtract(a).equals(Q("1.5")), a.multiply("2").equals(Q("2.5")), a.compareTo(b), Quantity.zero("shares").isZero(), String(a)]).toEqual([true, true, true, -1, true, "1.25 shares"]);
E(() => a.add(Q("1", "contracts"))).toThrow(UnitMismatchError);
for (const [inp, exp] of [["1234567", "1,234,567"], [D("1234.50"), "1,234.50"], ["0.123456789", "0.123456789"], ["10.5", "10.50"], ["-1200.25", "-1,200.25"]] as const) E(formatQuantity(inp)).toBe(exp);
E(() => formatQuantity("Infinity")).toThrow(FloatNotAllowedError);
// @ts-expect-error numbers rejected
E(() => formatQuantity(Infinity)).toThrow(FloatNotAllowedError);
});
