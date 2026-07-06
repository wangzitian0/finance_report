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
