// Text labels that back colour-coded financial status, so state is never
// conveyed by colour alone (WCAG 1.4.1, issue #1609).

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
