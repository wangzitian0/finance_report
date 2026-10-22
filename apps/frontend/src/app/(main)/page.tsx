"use client";

import { useMemo } from "react";

import { AdvisorBrief } from "@/components/advisor/AdvisorBrief";
import { HomeActionBanner } from "@/components/home/HomeActionBanner";
import { ReportDimensionBar } from "@/components/reports/ReportFilters";
import { StatementCockpit } from "@/components/reports/StatementCockpit";
import { useApiQuery } from "@/hooks/useApiQuery";
import { useReportFilters } from "@/hooks/useReportFilters";
import { normalizeAdvisorSuggestions } from "@/lib/types";

/** Stale time of the advisor suggestions. The server builds a full report package for them. */
const ADVISOR_SUGGESTIONS_STALE_MS = 5 * 60 * 1000;

/**
 * Home: one period-driven three-statement cockpit (#2621 LC, #2548 P1).
 *
 * The dimension bar sets the period and the currency in the URL. The cockpit shows the three
 * statements of that period. Workflow items show only as one banner, and only when an item
 * needs the user. The advisor suggestions load off the critical path: no card waits for them.
 */
export default function HomePage() {
  const filters = useReportFilters();
  const suggestionsQuery = useApiQuery(
    ["chat", "suggestions", { language: "en", includeStructured: true }],
    "suggestions_chat_suggestions_get",
    { query: { language: "en", include_structured: true } },
    { staleTime: ADVISOR_SUGGESTIONS_STALE_MS, retry: false },
  );
  const structuredSuggestions = suggestionsQuery.data?.structured_suggestions;
  const advisorSuggestions = useMemo(() => normalizeAdvisorSuggestions(structuredSuggestions), [structuredSuggestions]);

  return (
    <div className="space-y-4 p-6">
      <h1 className="sr-only">Home</h1>
      <HomeActionBanner />
      <ReportDimensionBar filters={filters} showScope />
      <StatementCockpit filters={filters} />
      {advisorSuggestions.length > 0 ? <AdvisorBrief suggestions={advisorSuggestions} /> : null}
    </div>
  );
}
