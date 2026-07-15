import { describe, it, expect } from "vitest";

import {
    checkSeverityColor,
    checkTypeLabel,
    confidenceLabel,
    countLabel,
    coverageLabel,
    currencyCodeOrDash,
    humanizeIdentifier,
    pnlColorClass,
    readinessVariant,
    sourceClassLabel,
} from "@/lib/statusLabels";

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

// #1868 S5 PR-B: helpers single-homed from component-local duplicates.
describe("statusLabels — single-homed helpers (#1868 S5)", () => {
    it("currencyCodeOrDash returns the code, or a dash when unset", () => {
        expect(currencyCodeOrDash("SGD")).toBe("SGD");
        expect(currencyCodeOrDash(null)).toBe("—");
        expect(currencyCodeOrDash(undefined)).toBe("—");
    });

    it("countLabel pluralizes on count, with a default and an explicit plural", () => {
        expect(countLabel(1, "item")).toBe("1 item");
        expect(countLabel(3, "item")).toBe("3 items");
        expect(countLabel(0, "blocked", "blocked")).toBe("0 blocked");
        expect(countLabel(2, "blocked", "blocked")).toBe("2 blocked");
    });

    it("pnlColorClass signals positive/negative/zero by class", () => {
        expect(pnlColorClass("10.00")).toBe("text-[var(--success)]");
        expect(pnlColorClass("-10.00")).toBe("text-[var(--error)]");
        expect(pnlColorClass("0")).toBe("");
    });

    it("humanizeIdentifier title-cases and preserves known acronyms", () => {
        expect(humanizeIdentifier("csv_export")).toBe("CSV Export");
        expect(humanizeIdentifier("bank-statement")).toBe("Bank Statement");
        expect(humanizeIdentifier(null)).toBe("Not recorded");
        expect(humanizeIdentifier("")).toBe("Not recorded");
    });

    it("sourceClassLabel prefers the known map, falls back to humanizeIdentifier", () => {
        expect(sourceClassLabel("bank_statement")).toBe("Bank statements");
        expect(sourceClassLabel("manual_valuation_snapshot")).toBe("Manual valuation snapshots");
        expect(sourceClassLabel("unknown_source")).toBe("Unknown Source");
    });

    it("checkSeverityColor/checkTypeLabel cover the stage2 consistency-check vocabulary", () => {
        expect(checkSeverityColor("high")).toBe("text-[var(--error)]");
        expect(checkSeverityColor("medium")).toBe("text-[var(--warning)]");
        expect(checkSeverityColor("low")).toBe("text-muted");
        expect(checkTypeLabel("duplicate")).toBe("Duplicate");
        expect(checkTypeLabel("transfer_pair")).toBe("Transfer Pair");
        expect(checkTypeLabel("anomaly")).toBe("Anomaly");
        expect(checkTypeLabel("manual_review")).toBe("manual_review");
    });

    // G-one-readiness-language (#1868 S5): the union of
    // PersonalReportPackageReadinessResponse["state"] and
    // WorkflowReportReadinessState, pinned so the two surfaces that
    // previously disagreed (reports/page.tsx vs WorkflowNotifications.tsx)
    // can never diverge again.
    it("readinessVariant pins a color for every state in the unioned enum", () => {
        expect(readinessVariant("ready")).toBe("success");
        expect(readinessVariant("generated")).toBe("success");
        expect(readinessVariant("blocked")).toBe("error");
        expect(readinessVariant("stale")).toBe("error");
        expect(readinessVariant("processing")).toBe("warning");
        expect(readinessVariant("draft")).toBe("muted");
        expect(readinessVariant("none")).toBe("info");
    });
});
