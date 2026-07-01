import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

import {
  FloatNotAllowedError,
  InvalidUnitError,
  QUANTITY_DP,
  QUANTITY_QUANTUM,
  QUANTITY_ROUNDING,
  Quantity,
  Unit,
  UnitMismatchError,
  formatQuantity,
} from "./index";

const here = dirname(fileURLToPath(import.meta.url));
const vectorsPath = resolve(here, "../../../../../../common/audit/quantity/conformance/vectors.json");
const VECTORS = JSON.parse(readFileSync(vectorsPath, "utf-8")) as {
  quantity_quantum: string;
  quantity_dp: number;
  default_rounding: string;
  unit_normalize: { input: string; expected: string }[];
  unit_invalid: string[];
  quantize: { value: string; unit: string; expected: string }[];
  ratio: { part: string; whole: string; unit: string; expected_percent_2dp: string }[];
};

describe("quantity conformance (cross-language standard AC12.30)", () => {
  it("AC12.30.2 declares the same quantum and default rounding", () => {
    expect(QUANTITY_DP).toBe(VECTORS.quantity_dp);
    expect(QUANTITY_QUANTUM.equals(new Decimal(VECTORS.quantity_quantum))).toBe(true);
    expect(QUANTITY_ROUNDING).toBe(Decimal.ROUND_HALF_UP);
    expect(VECTORS.default_rounding).toBe("ROUND_HALF_UP");
  });

  it("AC12.30.2 matches every quantize vector", () => {
    for (const c of VECTORS.quantize) {
      const got = new Quantity(c.value, c.unit).quantize().value;
      expect(got.equals(new Decimal(c.expected)), JSON.stringify(c)).toBe(true);
    }
  });

  it("AC12.30.2 normalizes and rejects units per the standard", () => {
    for (const c of VECTORS.unit_normalize) {
      expect(new Unit(c.input).code).toBe(c.expected);
    }
    for (const bad of VECTORS.unit_invalid) {
      expect(() => new Unit(bad)).toThrow(InvalidUnitError);
    }
    const unit = new Unit("shares");
    expect(Unit.of(unit)).toBe(unit);
    expect(Unit.of("SHARES").equals(unit)).toBe(true);
    expect(String(unit)).toBe("shares");
  });

  it("AC12.30.1 AC12.30.2 derives ratios from same-unit quantities", () => {
    for (const c of VECTORS.ratio) {
      const got = new Quantity(c.part, c.unit).ratioTo(new Quantity(c.whole, c.unit));
      expect(got.toPercent().equals(new Decimal(c.expected_percent_2dp)), JSON.stringify(c)).toBe(true);
    }
  });
});

describe("quantity value-type laws (TS rendering of the contract)", () => {
  it("AC12.30.1 rejects JS number values", () => {
    // @ts-expect-error number is intentionally not assignable to QuantityInput
    expect(() => new Quantity(0.125, "shares")).toThrow(FloatNotAllowedError);
    expect(() => new Quantity("Infinity", "shares")).toThrow(FloatNotAllowedError);
  });

  it("AC12.30.1 guards same-unit arithmetic and comparison", () => {
    const a = new Quantity("1.25", "shares");
    const b = new Quantity("2.75", "shares");
    const decimalInput = new Quantity(new Decimal("1.2345675"), "shares");
    expect(decimalInput.quantize(Decimal.ROUND_HALF_DOWN).value.equals(new Decimal("1.234567"))).toBe(true);
    expect(a.add(b).equals(new Quantity("4", "shares"))).toBe(true);
    expect(b.subtract(a).equals(new Quantity("1.5", "shares"))).toBe(true);
    expect(a.multiply("2").equals(new Quantity("2.5", "shares"))).toBe(true);
    expect(a.compareTo(b)).toBe(-1);
    expect(Quantity.zero("shares").isZero()).toBe(true);
    expect(String(a)).toBe("1.25 shares");
    expect(() => a.add(new Quantity("1", "contracts"))).toThrow(UnitMismatchError);
  });

  it("AC12.30.4 formats quantities from the quantity package", () => {
    expect(formatQuantity("1234567")).toBe("1,234,567");
    expect(formatQuantity(new Decimal("1234.50"))).toBe("1,234.50");
    expect(formatQuantity("0.123456789")).toBe("0.123456789");
    expect(formatQuantity("10.5")).toBe("10.50");
    expect(formatQuantity("-1200.25")).toBe("-1,200.25");
    expect(() => formatQuantity("Infinity")).toThrow(FloatNotAllowedError);
    // @ts-expect-error numbers are not accepted at the quantity boundary
    expect(() => formatQuantity(Infinity)).toThrow(FloatNotAllowedError);
  });
});
