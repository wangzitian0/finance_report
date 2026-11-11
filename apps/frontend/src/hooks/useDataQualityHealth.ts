"use client";

import { useApiQuery } from "@/hooks/useApiQuery";
import type { QualityGrade } from "@/lib/types";

export const DATA_QUALITY_HEALTH_QUERY_KEY = ["reports", "data-quality"] as const;

const GRADE_META: Record<QualityGrade, { color: string; label: string }> = {
  A_AUDIT_READY: { color: "var(--success)", label: "Grade A · Audit-Ready" },
  B_BALANCED_GAPS: { color: "var(--accent)", label: "Grade B · Balanced with Gaps" },
  C_ATTENTION_NEEDED: { color: "var(--warning)", label: "Grade C · Attention Needed" },
  D_OUT_OF_BALANCE: { color: "var(--error)", label: "Grade D · Out of Balance" },
};

export function useDataQualityHealth(asOfDate?: string, currency?: string) {
  return useApiQuery(
    [...DATA_QUALITY_HEALTH_QUERY_KEY, asOfDate, currency],
    "get_data_quality_health_reports_data_quality_get",
    { query: { as_of_date: asOfDate, currency } },
    { staleTime: 30_000, refetchOnWindowFocus: true },
  );
}

export function getGradeColor(grade: QualityGrade): string {
  return GRADE_META[grade]?.color ?? "var(--muted)";
}

export function getGradeLabel(grade: QualityGrade): string {
  return GRADE_META[grade]?.label ?? "Unclassified";
}
