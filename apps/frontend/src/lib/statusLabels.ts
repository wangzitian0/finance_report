import { compareAmounts } from "@/lib/audit/money";
import type { BadgeVariant } from "@/components/ui";

// Text labels that back colour-coded financial status, so state is never
// conveyed by colour alone (WCAG 1.4.1, issue #1609).

/**
 * Report-readiness state -> Badge color, the union of the two report-package
 * readiness state enums (`PersonalReportPackageReadinessResponse["state"]`
 * and `WorkflowReportReadinessState`). Was two near-duplicate
 * `readinessVariant` functions (reports/page.tsx, WorkflowNotifications.tsx)
 * that assigned CONFLICTING colors to their "unhandled" defaults — but the
 * two enums don't actually overlap on the states each treats as a default
 * (reports/page.tsx never sees `none`; the workflow status never sees
 * `draft`/`generated`), so every state below is mapped explicitly and no
 * default/fallback branch is needed (#1868 S5).
 */
const READINESS_VARIANTS: Record<
    "ready" | "generated" | "blocked" | "stale" | "processing" | "draft" | "none",
    BadgeVariant
> = {
    ready: "success",
    generated: "success",
    blocked: "error",
    stale: "error",
    processing: "warning",
    draft: "muted",
    none: "info",
};

export function readinessVariant(state: keyof typeof READINESS_VARIANTS): BadgeVariant {
    return READINESS_VARIANTS[state];
}

/** A currency code, or an em dash while unknown (was duplicated under the
 * name `formatCurrency` in upload/page.tsx — collided in name, though not
 * meaning, with lib/audit/money/format.ts's amount-formatting
 * `formatCurrency`, #1868 S5). */
export function currencyCodeOrDash(currency?: string | null): string {
    return currency || "—";
}

/** Pluralize a count: "1 item" / "3 items" (default plural is `${singular}s`). */
export function countLabel(count: number, singular: string, plural = `${singular}s`): string {
    return `${count} ${count === 1 ? singular : plural}`;
}

/** Text color class for a signed money amount: positive/negative/zero. */
export function pnlColorClass(value: string): string {
    const comparison = compareAmounts(value, "0");
    if (comparison === 0) return "";
    return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

const SOURCE_CLASS_LABELS: Record<string, string> = {
    bank_statement: "Bank statements",
    brokerage_statement: "Brokerage statements",
    settlement_note: "Settlement notes",
    esop_rsu_plan: "ESOP / RSU plans",
    property_statement: "Property statements",
    liability_statement: "Liability statements",
    csv_export: "CSV exports",
    manual_record: "Manual records",
    manual_valuation_snapshot: "Manual valuation snapshots",
    package_contract: "Package contract",
};

const ACRONYMS = new Set(["AI", "CSV", "ESOP", "FX", "GAAP", "HK", "LLM", "OCR", "PR", "RSU", "US"]);

/** Title-case an identifier, preserving known acronyms ("csv_export" -> "CSV Export"). */
export function humanizeIdentifier(value?: string | null): string {
    if (!value) return "Not recorded";
    const spaced = value.replace(/[._-]+/g, " ").trim();
    if (!spaced) return "Not recorded";
    return spaced
        .split(/\s+/)
        .map((word) => {
            const upper = word.toUpperCase();
            if (ACRONYMS.has(upper)) return upper;
            return `${word.slice(0, 1).toUpperCase()}${word.slice(1).toLowerCase()}`;
        })
        .join(" ");
}

/** Display label for a source-document class, e.g. "bank_statement" -> "Bank statements". */
export function sourceClassLabel(sourceClass: string): string {
    return SOURCE_CLASS_LABELS[sourceClass] ?? humanizeIdentifier(sourceClass);
}

/** Parse-confidence tier label for a 0-100 score. */
export function confidenceLabel(score: number): string {
    if (score >= 85) return "Good";
    if (score >= 60) return "Fair — review advised";
    return "Low — review required";
}

/** Reconciliation-coverage tier label for a 0-100 percentage. */
export function coverageLabel(pct: number): string {
    if (pct >= 85) return "Good";
    if (pct >= 60) return "Fair";
    return "Needs attention";
}

/** Stage-2 consistency-check severity color (was components/review/stage2/types.ts). */
export function checkSeverityColor(severity: string): string {
    switch (severity) {
        case "high":
            return "text-[var(--error)]";
        case "medium":
            return "text-[var(--warning)]";
        default:
            return "text-muted";
    }
}

/** Stage-2 consistency-check type display label (was components/review/stage2/types.ts). */
export function checkTypeLabel(type: string): string {
    switch (type) {
        case "duplicate":
            return "Duplicate";
        case "transfer_pair":
            return "Transfer Pair";
        case "anomaly":
            return "Anomaly";
        default:
            return type;
    }
}
