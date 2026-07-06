import { describe, it, expect } from "vitest";

import { confidenceLabel, coverageLabel } from "@/lib/statusLabels";

describe("statusLabels (#1609 colour-not-alone)", () => {
    it("confidenceLabel covers every tier", () => {
        expect(confidenceLabel(92)).toBe("Good");
        expect(confidenceLabel(85)).toBe("Good");
        expect(confidenceLabel(70)).toBe("Fair — review advised");
        expect(confidenceLabel(60)).toBe("Fair — review advised");
        expect(confidenceLabel(40)).toBe("Low — review required");
    });

    it("coverageLabel covers every tier", () => {
        expect(coverageLabel(90)).toBe("Good");
        expect(coverageLabel(85)).toBe("Good");
        expect(coverageLabel(72)).toBe("Fair");
        expect(coverageLabel(60)).toBe("Fair");
        expect(coverageLabel(30)).toBe("Needs attention");
    });
});
