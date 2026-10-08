// AC-reporting.fe-report-surfaces.1: Liability tone styling for zero vs positive liabilities
import { describe, expect, it } from "vitest";
import { liabilityToneClass } from "@/lib/statusLabels";

describe("liabilityToneClass (BUG-05 zero liabilities neutral tone)", () => {
  it("returns neutral text-muted class when liabilities are 0", () => {
    expect(liabilityToneClass("0")).toBe("text-muted");
    expect(liabilityToneClass("0.00")).toBe("text-muted");
    expect(liabilityToneClass(0)).toBe("text-muted");
    expect(liabilityToneClass(null)).toBe("text-muted");
  });

  it("returns alarming text-[var(--error)] class only when liabilities are positive", () => {
    expect(liabilityToneClass("500.00")).toBe("text-[var(--error)]");
    expect(liabilityToneClass("0.01")).toBe("text-[var(--error)]");
  });
});
