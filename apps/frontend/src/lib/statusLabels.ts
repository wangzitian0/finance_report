import { compareAmounts } from "@/lib/audit/money";

// Text labels that back colour-coded financial status, so state is never
// conveyed by colour alone (WCAG 1.4.1, issue #1609).

/**
 * Visual status tone corresponding to semantic status colors.
 * Defined in lib/ to avoid reverse dependency from lib -> components/ui.
 * Structurally compatible with BadgeVariant.
 */
export type StatusTone = "success" | "error" | "warning" | "muted" | "info";

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
    StatusTone
> = {
    ready: "success",
    generated: "success",
    blocked: "error",
    stale: "error",
    processing: "warning",
    draft: "muted",
    none: "info",
};

export function readinessVariant(state: keyof typeof READINESS_VARIANTS): StatusTone {
    return READINESS_VARIANTS[state];
}

/** A currency code, or an em dash while unknown (was duplicated under the
 * name `formatCurrency` in upload/page.tsx, #1868 S5). */
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

/** Text color class for liability amount: error when positive liability exists, neutral when zero. */
export function liabilityToneClass(value?: string | number | null): string {
    if (!value) return "text-muted";
    const comparison = compareAmounts(String(value), "0");
    return comparison > 0 ? "text-[var(--error)]" : "text-muted";
}

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

/** Display label of a net worth allocation class, e.g. "real_estate" -> "Real Estate". */
export function allocationClassLabel(value: string): string {
    if (value === "retirement_and_benefit_assets") return "Retirement & Benefit Assets";
    return humanizeIdentifier(value);
}

/** Parse-confidence tier label for a 0-100 score. */
export function confidenceLabel(score: number): string {
    if (score >= 85) return "Good";
    if (score >= 60) return "Fair — review advised";
    return "Low — review required";
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

export const PARSING_POLL_MS = 3000;

/** Canonical statement display title shared by `/upload` and `/statements/[id]`. */
export function statementDisplayTitle(statement: {
    original_filename?: string | null;
    institution?: string | null;
    period_start?: string | null;
    period_end?: string | null;
}): string {
    return statement.original_filename || `${statement.institution ?? ""} (${statement.period_start ?? ""} – ${statement.period_end ?? ""})`;
}

const BROKERAGE_ALIASES = ["interactive brokers", "ibkr", "ib llc", "moomoo", "futu sg", "futu", "富途"];

/** True when the statement belongs to a brokerage positions source (#2729). */
export function canImportBrokerageStatement(statement: {
    institution?: string | null;
    original_filename?: string | null;
    brokerage_import_failed?: boolean | null;
}): boolean {
    if (statement.brokerage_import_failed) return true;
    const haystack = `${statement.institution ?? ""} ${statement.original_filename ?? ""}`.toLowerCase();
    return BROKERAGE_ALIASES.some((alias) => haystack.includes(alias));
}

/** Reader-facing label for a report account name: the Processing clearing account is shown as Transfers in transit (#2728). */
export function reportAccountDisplayName(name: string): string {
    return name === "Processing" ? "Transfers in transit" : name;
}

const SYSTEM_ACCOUNT_CODE_LABELS: Record<string, string> = {
    "AUTO-ASSET": "Auto-created",
    "SYS-PROCESSING": "System clearing",
    "AUTO-EQUITY-OPENING": "Opening equity",
    "AUTO-BANK": "Auto bank",
    "SYS-FX-REVAL": "FX revaluation",
};

/** Reader-facing label for an account code badge: humanizes internal system codes while preserving user codes (#2650). */
export function formatAccountCodeBadge(code: string): string {
    return SYSTEM_ACCOUNT_CODE_LABELS[code] ?? code;
}
