import Decimal from "decimal.js";

/**
 * Shared wire-boundary codec for the audit value types (Money/Quantity/Ratio).
 * `decimalToWire` is byte-identical across all three; `decimalStringFromWire`
 * is structurally identical, differing only in which package-typed error
 * class each throws on a float/malformed value — parameterized here instead
 * of copy-pasted (#1868 S5; mirrors the backend `WireCodec` pattern in
 * common/audit/decimal_scalar.py).
 */

/** Format a Decimal for the wire: trimmed, no trailing zeros, "0" for zero. */
export function decimalToWire(value: Decimal): string {
  return value.isZero() ? "0" : value.toFixed().replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

/**
 * Decode+validate a wire decimal string: rejects a JS number (float) and a
 * non-finite value. `FloatError`/`PayloadError` are the caller's own typed
 * error classes (e.g. money's `FloatNotAllowedError`/`InvalidMoneyPayloadError`).
 */
export function decimalStringFromWire(
  value: unknown,
  what: string,
  FloatError: new (message: string) => Error,
  PayloadError: new (message: string) => Error,
): string {
  if (typeof value === "number") {
    throw new FloatError(`${what} must be encoded as a decimal string, not a number`);
  }
  if (typeof value !== "string") {
    throw new FloatError(`${what} must be encoded as a decimal string`);
  }
  try {
    const parsed = new Decimal(value);
    if (!parsed.isFinite()) throw new FloatError(`${what} must be finite`);
  } catch (error) {
    if (error instanceof FloatError) throw error;
    throw new PayloadError(`${what} is not a valid decimal string`);
  }
  return value;
}
