import Decimal from "decimal.js";

import { Ratio } from "@/lib/ratio";

import { FloatNotAllowedError, InvalidQuantityPayloadError, InvalidUnitError, UnitMismatchError } from "./errors";

export const QUANTITY_DP = 6;
export const QUANTITY_QUANTUM = new Decimal("0.000001");
export const QUANTITY_ROUNDING: Decimal.Rounding = Decimal.ROUND_HALF_UP;

export type QuantityInput = Decimal | string;
export type QuantityWire = { value: string; unit: string };

const UNIT_RE = /^[a-z][a-z0-9_-]*$/;

function coerce(value: QuantityInput, what = "quantity value"): Decimal {
  let d: Decimal;
  if (value instanceof Decimal) {
    d = value;
  } else if (typeof value === "string") {
    d = new Decimal(value);
  } else {
    throw new FloatNotAllowedError(`${what} must be a Decimal or decimal string, not a number`);
  }
  if (!d.isFinite()) throw new FloatNotAllowedError(`${what} must be finite`);
  return d;
}

function decimalToWire(value: Decimal): string {
  return value.isZero() ? "0" : value.toString();
}

function recordFromWire(payload: unknown): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new InvalidQuantityPayloadError("Quantity payload must be an object");
  }
  return payload as Record<string, unknown>;
}

function stringField(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  if (typeof value !== "string") {
    throw new InvalidQuantityPayloadError(`Quantity payload field ${key} must be a string`);
  }
  return value;
}

function decimalStringFromWire(value: unknown, what = "quantity value"): string {
  if (typeof value === "number") {
    throw new FloatNotAllowedError(`${what} must be encoded as a decimal string, not a number`);
  }
  if (typeof value !== "string") {
    throw new FloatNotAllowedError(`${what} must be encoded as a decimal string`);
  }
  try {
    const parsed = new Decimal(value);
    if (!parsed.isFinite()) throw new FloatNotAllowedError(`${what} must be finite`);
  } catch (error) {
    if (error instanceof FloatNotAllowedError) throw error;
    throw new InvalidQuantityPayloadError(`${what} is not a valid decimal string`);
  }
  return value;
}

export class Unit {
  readonly code: string;

  constructor(code: string) {
    const normalized = code.trim().toLowerCase();
    if (!UNIT_RE.test(normalized)) {
      throw new InvalidUnitError(`invalid quantity unit: ${code}`);
    }
    this.code = normalized;
    Object.freeze(this);
  }

  static of(value: Unit | string): Unit {
    return value instanceof Unit ? value : new Unit(value);
  }

  equals(other: Unit): boolean {
    return this.code === other.code;
  }

  toString(): string {
    return this.code;
  }
}

export class Quantity {
  readonly value: Decimal;
  readonly unit: Unit;

  constructor(value: QuantityInput, unit: Unit | string) {
    this.value = coerce(value);
    this.unit = Unit.of(unit);
    Object.freeze(this);
  }

  static zero(unit: Unit | string): Quantity {
    return new Quantity("0", unit);
  }

  isZero(): boolean {
    return this.value.isZero();
  }

  quantize(rounding: Decimal.Rounding = QUANTITY_ROUNDING): Quantity {
    return new Quantity(this.value.toDecimalPlaces(QUANTITY_DP, rounding), this.unit);
  }

  private requireSameUnit(other: Quantity, op: string): void {
    if (!this.unit.equals(other.unit)) {
      throw new UnitMismatchError(`cannot ${op} across units: ${this.unit.code} and ${other.unit.code}`);
    }
  }

  add(other: Quantity): Quantity {
    this.requireSameUnit(other, "add");
    return new Quantity(this.value.plus(other.value), this.unit);
  }

  subtract(other: Quantity): Quantity {
    this.requireSameUnit(other, "subtract");
    return new Quantity(this.value.minus(other.value), this.unit);
  }

  multiply(factor: QuantityInput): Quantity {
    return new Quantity(this.value.times(coerce(factor, "factor")), this.unit);
  }

  compareTo(other: Quantity): number {
    this.requireSameUnit(other, "compare");
    return this.value.comparedTo(other.value);
  }

  equals(other: Quantity): boolean {
    return this.unit.equals(other.unit) && this.value.equals(other.value);
  }

  ratioTo(whole: Quantity): Ratio {
    this.requireSameUnit(whole, "divide");
    return Ratio.fraction(this.value, whole.value);
  }

  toString(): string {
    return `${this.value.toString()} ${this.unit.code}`;
  }
}

export function quantity_to_wire(quantity: Quantity): QuantityWire {
  if (!(quantity instanceof Quantity)) {
    throw new TypeError("quantity_to_wire expects Quantity");
  }
  return { value: decimalToWire(quantity.value), unit: quantity.unit.code };
}

export function quantity_from_wire(payload: unknown): Quantity {
  const fields = recordFromWire(payload);
  return new Quantity(decimalStringFromWire(fields.value), stringField(fields, "unit"));
}
