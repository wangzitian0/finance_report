"use client";

import { useApiQuery } from "@/hooks/useApiQuery";
import type { PersonalDataQualityHealthResponse, QualityGrade } from "@/lib/types";

export const DATA_QUALITY_HEALTH_QUERY_KEY = ["reports", "data-quality"] as const;

export function useDataQualityHealth(asOfDate?: string, currency?: string) {
  const query = useApiQuery(
    [...DATA_QUALITY_HEALTH_QUERY_KEY, asOfDate, currency],
    "get_data_quality_health_reports_data_quality_get",
    {
      query: {
        as_of_date: asOfDate,
        currency,
      },
    },
    {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  );

  return query;
}

export function getGradeColor(grade: QualityGrade): string {
  switch (grade) {
    case "A_AUDIT_READY":
      return "var(--success)";
    case "B_BALANCED_GAPS":
      return "var(--accent)";
    case "C_ATTENTION_NEEDED":
      return "var(--warning)";
    case "D_OUT_OF_BALANCE":
      return "var(--error)";
    default:
      return "var(--muted)";
  }
}

export function getGradeLabel(grade: QualityGrade): string {
  switch (grade) {
    case "A_AUDIT_READY":
      return "Grade A · Audit-Ready";
    case "B_BALANCED_GAPS":
      return "Grade B · Balanced with Gaps";
    case "C_ATTENTION_NEEDED":
      return "Grade C · Attention Needed";
    case "D_OUT_OF_BALANCE":
      return "Grade D · Out of Balance";
    default:
      return "Unclassified";
  }
}
