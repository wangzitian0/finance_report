import { describe, it, expect } from "vitest";
import { formatDateInput, formatDateDisplay, formatDateTimeDisplay, formatMonthLabel } from "../lib/date";

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

describe("formatDateDisplay", () => {
    it("formats a Date object to en-US short date", () => {
        const result = formatDateDisplay(new Date(2024, 0, 15));
        expect(result).toContain("Jan");
        expect(result).toContain("15");
        expect(result).toContain("2024");
    });

    it("formats a date-only string (YYYY-MM-DD) correctly", () => {
        const result = formatDateDisplay("2024-03-05");
        expect(result).toContain("Mar");
        expect(result).toContain("5");
        expect(result).toContain("2024");
    });

    it("formats an ISO datetime string with T separator", () => {
        const result = formatDateDisplay("2024-06-15T10:30:00Z");
        expect(result).toContain("Jun");
        expect(result).toContain("2024");
    });
});

describe("formatDateTimeDisplay", () => {
    it("formats a Date object with date and time", () => {
        const result = formatDateTimeDisplay(new Date(2024, 5, 15, 14, 30));
        expect(result).toContain("Jun");
        expect(result).toContain("15");
        expect(result).toContain("2024");
    });

    it("formats an ISO datetime string", () => {
        const result = formatDateTimeDisplay("2024-03-05T10:30:00Z");
        expect(result).toContain("Mar");
        expect(result).toContain("2024");
    });
});

describe("formatMonthLabel", () => {
    it("returns short month name from date string", () => {
        expect(formatMonthLabel("2024-01-15")).toContain("Jan");
        expect(formatMonthLabel("2024-06-01")).toContain("Jun");
        expect(formatMonthLabel("2024-12-31")).toContain("Dec");
    });
});
