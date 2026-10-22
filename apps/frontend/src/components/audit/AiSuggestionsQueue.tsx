"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiOperation } from "@/lib/api-client";
import { getCategoriesForDirection } from "@/lib/categories";
import { BackLink } from "@/components/ui/SmartBackLink";
import type { AiSuggestion } from "@/lib/types";

type FeedbackAction = "accept" | "reject" | "edit_accept";

const EFFECT_LABEL: Record<string, string> = {
  accepted: "Accepted. The one-click approval of the statement posts it.",
  rejected: "Rejected. The approval uses the default category.",
  corrected: "Corrected. The one-click approval posts your category.",
  recorded: "Feedback saved. It did not change the suggestion.",
};

/** Pending AI suggestions that the user accepts, rejects or corrects. */
export function AiSuggestionsQueue() {
  const searchParams = useSearchParams();
  const statementId = searchParams?.get("statement_id")?.trim() || undefined;
  const returnTo = searchParams?.get("return_to")?.trim() || undefined;
  const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
  const [correctedValues, setCorrectedValues] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const data = statementId
        ? await apiOperation("list_ai_suggestions_ai_suggestions_get", { query: { statement_id: statementId } })
        : await apiOperation("list_ai_suggestions_ai_suggestions_get");
      setSuggestions(data.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load AI suggestions");
    } finally {
      setLoading(false);
    }
  }, [statementId]);

  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  const submitFeedback = async (suggestion: AiSuggestion, action: FeedbackAction) => {
    const id = suggestion.suggestion_id;
    const corrected = correctedValues[id]?.trim();
    setSaving((c) => ({ ...c, [id]: true }));
    try {
      const saved = await apiOperation("create_ai_feedback_ai_feedback_post", {
        body: { suggestion_id: id, action, ...(action === "edit_accept" && corrected ? { corrected_value: { value: corrected } } : {}) },
      });
      setRowErrors(({ [id]: _cleared, ...rest }) => rest);
      setDecisions((c) => ({ ...c, [id]: EFFECT_LABEL[saved?.effect ?? "recorded"] ?? EFFECT_LABEL.recorded }));
    } catch (err) {
      setRowErrors((c) => ({ ...c, [id]: err instanceof Error ? err.message : "Failed to save your decision" }));
    } finally {
      setSaving(({ [id]: _done, ...rest }) => rest);
    }
  };

  const renderCorrectionInput = (suggestion: AiSuggestion, surface: "mobile" | "table") => {
    const inputId = `corrected-${surface}-${suggestion.suggestion_id}`;
    const options = getCategoriesForDirection(suggestion.direction);
    return (
      <>
        <label className="sr-only" htmlFor={inputId}>Corrected value</label>
        <select
          id={inputId}
          aria-label="Corrected value"
          className="input py-2 text-sm"
          value={correctedValues[suggestion.suggestion_id] ?? ""}
          onChange={(e) => setCorrectedValues((c) => ({ ...c, [suggestion.suggestion_id]: e.target.value }))}
        >
          <option value="">Select category...</option>
          {options.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
        </select>
      </>
    );
  };

  const renderActionButtons = (suggestion: AiSuggestion, className = "") => (
    <div className={`grid grid-cols-2 gap-2 sm:flex sm:justify-end ${className}`}>
      <button type="button" className="btn-primary text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "accept")}>Accept</button>
      <button type="button" className="btn-secondary text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "reject")}>Reject</button>
      <button type="button" className="btn-secondary col-span-2 text-xs whitespace-nowrap" disabled={saving[suggestion.suggestion_id]} onClick={() => submitFeedback(suggestion, "edit_accept")}>Edit-then-Accept</button>
    </div>
  );

  const renderOutcome = (suggestion: AiSuggestion) => (
    <div className="mt-1 min-h-[1rem] text-xs sm:text-right">
      <p role="status" aria-live="polite" className="text-muted">{saving[suggestion.suggestion_id] ? "Saving..." : (decisions[suggestion.suggestion_id] ?? "")}</p>
      {rowErrors[suggestion.suggestion_id] && <p role="alert" className="text-[var(--error)]">{rowErrors[suggestion.suggestion_id]}</p>}
    </div>
  );

  if (loading) {
    return <section id="ai-suggestions"><div className="card p-6 text-center text-muted md:p-8">Loading AI suggestions...</div></section>;
  }

  return (
    <section id="ai-suggestions" className="space-y-3">
      {returnTo && <div><BackLink href="/audit">Back</BackLink></div>}
      <div>
        <h2 className="text-sm font-semibold">Suggestions to review</h2>
        <p className="text-xs text-muted">Approve or correct the AI&apos;s suggested categories and matches that need a human eye.</p>
      </div>
      {error && <div className="alert-error">{error}</div>}
      <div className="card overflow-hidden">
        {suggestions.length === 0 ? (
          <div className="p-8 text-center text-muted">No pending AI suggestions</div>
        ) : (
          <>
            <div data-testid="ai-suggestions-mobile-list" className="divide-y divide-[var(--border)] md:hidden">
              {suggestions.map((suggestion) => (
                <article key={suggestion.suggestion_id} data-testid={`ai-suggestion-mobile-card-${suggestion.suggestion_id}`} className="space-y-4 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><p className="text-xs font-medium uppercase text-muted">Transaction</p><p className="mt-1 break-words font-medium">{suggestion.transaction}</p></div>
                    <div className="flex-shrink-0 rounded-md bg-[var(--warning-muted)] px-2.5 py-1 text-sm font-semibold text-[var(--warning)]">{suggestion.ai_score}</div>
                  </div>
                  <div className="grid grid-cols-1 gap-3 text-sm">
                    <div><p className="text-xs font-medium uppercase text-muted">Suggestion</p><p className="mt-1 break-words">{suggestion.suggested_category_or_match}</p></div>
                    <div><p className="text-xs font-medium uppercase text-muted">Reasoning</p><p className="mt-1 break-words text-muted">{suggestion.ai_reasoning}</p></div>
                  </div>
                  <div className="space-y-3">{renderCorrectionInput(suggestion, "mobile")}{renderActionButtons(suggestion)}{renderOutcome(suggestion)}</div>
                </article>
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-[var(--background-muted)]/50 border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left px-4 py-3">Transaction</th>
                    <th className="text-left px-4 py-3">Suggestion</th>
                    <th className="text-left px-4 py-3">AI Score</th>
                    <th className="text-left px-4 py-3">AI Reasoning</th>
                    <th className="text-left px-4 py-3">Corrected value</th>
                    <th className="text-right px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {suggestions.map((suggestion) => (
                    <tr key={suggestion.suggestion_id}>
                      <td className="px-4 py-3 font-medium">{suggestion.transaction}</td>
                      <td className="px-4 py-3">{suggestion.suggested_category_or_match}</td>
                      <td className="px-4 py-3 text-[var(--warning)] font-semibold">{suggestion.ai_score}</td>
                      <td className="px-4 py-3 text-muted">{suggestion.ai_reasoning}</td>
                      <td className="px-4 py-3 min-w-[220px]">{renderCorrectionInput(suggestion, "table")}</td>
                      <td className="px-4 py-3 min-w-[240px]">{renderActionButtons(suggestion)}{renderOutcome(suggestion)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
