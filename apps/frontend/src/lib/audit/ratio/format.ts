import Decimal from "decimal.js";

import { Ratio, type RatioInput } from "./ratio";

type NullablePercentInput = RatioInput | null | undefined;

interface PercentFormatOptions {
  dp?: number;
  fallback?: string;
}

interface PercentNumberOptions {
  dp?: number;
  fallback?: number | null;
}

function normalizeInput(value: NullablePercentInput): RatioInput | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Decimal) return value;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function ratioFromRatioValue(value: NullablePercentInput): Ratio | null {
  const normalized = normalizeInput(value);
  if (normalized === null) return null;
  try {
    return new Ratio(normalized);
  } catch {
    return null;
  }
}

function ratioFromPercentValue(value: NullablePercentInput): Ratio | null {
  const normalized = normalizeInput(value);
  if (normalized === null) return null;
  try {
    return Ratio.fromPercent(normalized);
  } catch {
    return null;
  }
}

function formatRatioPercent(
  ratio: Ratio | null,
  dp: number,
  fallback: string,
  signed: boolean,
): string {
  if (ratio === null) return fallback;
  const percent = ratio.toPercent(dp);
  const sign = signed && percent.greaterThan(0) ? "+" : "";
  return `${sign}${percent.toFixed(dp)}%`;
}

export function formatPercentFromRatioValue(
  value: NullablePercentInput,
  options: PercentFormatOptions = {},
): string {
  const { dp = 2, fallback = "—" } = options;
  return formatRatioPercent(ratioFromRatioValue(value), dp, fallback, false);
}

export function formatPercentFromPercentValue(
  value: NullablePercentInput,
  options: PercentFormatOptions = {},
): string {
  const { dp = 2, fallback = "N/A" } = options;
  return formatRatioPercent(ratioFromPercentValue(value), dp, fallback, false);
}

export function formatSignedPercentFromPercentValue(
  value: NullablePercentInput,
  options: PercentFormatOptions = {},
): string {
  const { dp = 2, fallback = "N/A" } = options;
  return formatRatioPercent(ratioFromPercentValue(value), dp, fallback, true);
}

export function formatPercentValueFromParts(
  part: RatioInput,
  whole: RatioInput,
  options: PercentFormatOptions = {},
): string | null {
  const { dp = 2, fallback = "N/A" } = options;
  try {
    return Ratio.fraction(part, whole).toPercent(dp).toFixed(dp);
  } catch {
    return fallback === "N/A" ? null : fallback;
  }
}

export function percentNumberFromParts(
  part: RatioInput,
  whole: RatioInput,
  options: PercentNumberOptions = {},
): number | null {
  const { dp = 2, fallback = null } = options;
  try {
    return Ratio.fraction(part, whole).toPercent(dp).toNumber();
  } catch {
    return fallback;
  }
}

export function ratioNumberFromRatioValue(
  value: NullablePercentInput,
): number | null {
  const ratio = ratioFromRatioValue(value);
  return ratio === null ? null : ratio.value.toNumber();
}

export function percentNumberFromRatioValue(
  value: NullablePercentInput,
  options: PercentNumberOptions = {},
): number | null {
  const { dp = 2, fallback = null } = options;
  const ratio = ratioFromRatioValue(value);
  return ratio === null ? fallback : ratio.toPercent(dp).toNumber();
}

export function percentNumberFromPercentValue(
  value: NullablePercentInput,
  options: PercentNumberOptions = {},
): number | null {
  const { dp = 2, fallback = null } = options;
  const ratio = ratioFromPercentValue(value);
  return ratio === null ? fallback : ratio.toPercent(dp).toNumber();
}

export function clampPercentWidthFromPercentValue(
  value: NullablePercentInput,
): string {
  const percent =
    percentNumberFromPercentValue(value, { dp: 2, fallback: 0 }) ?? 0;
  const bounded = Math.min(100, Math.max(0, Math.abs(percent)));
  return `${new Decimal(bounded).toDecimalPlaces(2, Decimal.ROUND_HALF_UP).toString()}%`;
}
