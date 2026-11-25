import { expect, it } from "vitest";
import Decimal from "decimal.js";
import {
  compareAmounts,
  divideAmount,
  formatAmount,
  formatCurrencyLocale,
  isAmountZero,
  multiplyAmount,
  parseAmount,
  subtractAmounts,
  sumAmounts,
} from "./format";
const E = expect;
it("money/format AC-ledger.8.2", () => {
  for (const [v, e] of [
    ["100.50", "100.5"],
    ["-50.25", "-50.25"],
    [100.5, "100.5"],
    ["  100.50  ", "100.5"],
    ["999999999999.99", "999999999999.99"],
    ["0.000001", "0.000001"],
    ["1e10", "10000000000"],
    ["1.5e-3", "0.0015"],
  ] as const)
    E(parseAmount(v).toString()).toBe(e);
  for (const [m, xs] of [
    ["null or undefined", [null, undefined]],
    ["an empty string", ["", "   "]],
    ["a non-finite number", [NaN, Infinity, -Infinity]],
    ["an invalid type", [{}, [], true]],
  ] as const)
    for (const x of xs)
      E(() => parseAmount(x as never)).toThrow(`parseAmount received ${m}`);
  for (const [v, dp, e] of [
    [new Decimal(100.5), undefined, "100.50"],
    ["100.5", undefined, "100.50"],
    [100.5, 0, "101"],
    [new Decimal(100.5), 1, "100.5"],
    ["-50.25", 3, "-50.250"],
    ["100.555", 2, "100.56"],
    ["100.554", 2, "100.55"],
  ] as const)
    E(formatAmount(v, dp)).toBe(e);
  for (const [xs, e] of [
    [[], "0"],
    [[10, -5, "20.5", new Decimal("0.5")], "26"],
    [["0.1", "0.2"], "0.3"],
  ] as const)
    E(sumAmounts([...xs]).toString()).toBe(e);
  E(
    [
      subtractAmounts(100, 50),
      subtractAmounts(50, 100),
      subtractAmounts("100.5", "50.25"),
      multiplyAmount("10.5", "2"),
      divideAmount("10", "3"),
    ].map(String),
  ).toEqual(["50", "-50", "50.25", "21", "3.3333333333333333333"]);
  E([
    compareAmounts(10, 20),
    compareAmounts(10, 10),
    compareAmounts(20, 10),
    compareAmounts("100.0001", "100.0002"),
  ]).toEqual([-1, 0, 1, -1]);
  for (const [v, t, e] of [
    [0, undefined, true],
    ["0.01", undefined, true],
    ["-0.01", undefined, true],
    ["0.011", undefined, false],
    ["0.05", 0.1, true],
    ["0.15", 0.1, false],
    [new Decimal("0.005"), undefined, true],
    [new Decimal("0.02"), undefined, false],
  ] as const)
    E(isAmountZero(v, t)).toBe(e);
  for (const [v, o, e] of [
    ["9007199254740993.01", undefined, "$9,007,199,254,740,993.01"],
    [new Decimal("1234567.89"), { maximumFractionDigits: 0 }, "$1,234,568"],
    ["12.3400", { maximumFractionDigits: 4 }, "$12.34"],
    ["-42.50", undefined, "-$42.50"],
  ] as const)
    E(formatCurrencyLocale(v, "USD", "en-US", o)).toBe(e);
});
