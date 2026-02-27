import { describe, it, expect } from "vitest";
import { formatDateInput } from "../lib/date";

describe("formatDateInput", () => {
    it("AC16.6.1 formats a date as YYYY-MM-DD string", () => {
        const result = formatDateInput(new Date(2024, 0, 15));
        expect(result).toBe("2024-01-15");
    });

    it("AC16.6.1 pads single-digit month and day with zeros", () => {
        const result = formatDateInput(new Date(2024, 2, 5));
        expect(result).toBe("2024-03-05");
    });

    it("AC16.6.1 handles end of year dates correctly", () => {
        const result = formatDateInput(new Date(2023, 11, 31));
        expect(result).toBe("2023-12-31");
    });

    it("AC16.6.1 handles first day of year", () => {
        const result = formatDateInput(new Date(2025, 0, 1));
        expect(result).toBe("2025-01-01");
    });
});
