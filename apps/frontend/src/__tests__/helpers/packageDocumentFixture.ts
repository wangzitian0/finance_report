// Smallest package document that `normalizePersonalReportPackageDocument` accepts.
//
// The Reports hub and the package page read one cached preview through the same fetcher
// (#2583 S4), and that fetcher normalizes the document. A hub test therefore needs a
// document with the sections that the normalizer reads, not only a `readiness` object.

type Overrides = {
  readiness?: unknown;
  sections?: Record<string, unknown>;
  context?: Record<string, unknown>;
};

export function normalizablePackageDocument({
  readiness,
  sections = {},
  context = {},
}: Overrides = {}) {
  return {
    schema_version: "2",
    lifecycle: "preview",
    package_id: "personal-financial-report-package",
    context: { as_of_date: "2026-05-20", ...context },
    contract: { supported_frameworks: [] },
    readiness,
    framework_policy: { decisions: [], gaps: [], decision_count: 0, evidence_reference_count: 0 },
    sections: {
      balance_sheet: {},
      income_statement: {},
      cash_flow: {},
      ...sections,
    },
  };
}
