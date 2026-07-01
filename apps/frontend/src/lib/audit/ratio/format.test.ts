import { describe, expect, it } from "vitest";

import {
  clampPercentWidthFromPercentValue,
  formatPercentValueFromParts,
  formatPercentFromPercentValue,
  formatPercentFromRatioValue,
  formatSignedPercentFromPercentValue,
  percentNumberFromParts,
  percentNumberFromPercentValue,
  percentNumberFromRatioValue,
} from "./format";

describe("ratio percent formatting helpers (AC-audit.9.3)", () => {
  it("test_AC12_9_3_ratio_format_helpers_use_canonical_percent_policy", () => {
    expect(formatPercentFromRatioValue("0.12005")).toBe("12.01%");
    expect(formatPercentFromPercentValue("12.005")).toBe("12.01%");
    expect(formatPercentFromPercentValue("12.005", { dp: 1 })).toBe("12.0%");
    expect(formatSignedPercentFromPercentValue("8.25")).toBe("+8.25%");
    expect(formatSignedPercentFromPercentValue("-1.5")).toBe("-1.50%");
    expect(formatPercentValueFromParts("1", "8")).toBe("12.50");
    expect(formatPercentValueFromParts("1", "0")).toBeNull();
    expect(formatPercentValueFromParts("1", "0", { fallback: "—" })).toBe("—");
    expect(percentNumberFromParts("4", "7", { dp: 0 })).toBe(57);
    expect(percentNumberFromParts("4", "0", { dp: 0, fallback: 0 })).toBe(0);
  });

  it("test_AC12_9_3_ratio_format_helpers_guard_invalid_or_missing_inputs", () => {
    expect(formatPercentFromRatioValue("")).toBe("—");
    expect(formatPercentFromRatioValue("not-a-number")).toBe("—");
    expect(formatPercentFromRatioValue(0.125 as never)).toBe("—");
    expect(formatPercentFromPercentValue(null)).toBe("N/A");
    expect(formatPercentFromPercentValue(12.5 as never)).toBe("N/A");
    expect(formatSignedPercentFromPercentValue("not-a-number")).toBe("N/A");
  });

  it("test_AC12_9_3_ratio_format_helpers_return_chart_boundary_numbers", () => {
    expect(percentNumberFromRatioValue("0.125")).toBe(12.5);
    expect(percentNumberFromPercentValue("79.5", { dp: 0 })).toBe(80);
    expect(clampPercentWidthFromPercentValue("-150.00")).toBe("100%");
    expect(clampPercentWidthFromPercentValue("12.345")).toBe("12.35%");
    expect(clampPercentWidthFromPercentValue(null)).toBe("0%");
  });
});
