"use client";

import { useCallback, useEffect, useState } from "react";

import { apiOperation } from "@/lib/api-client";
import { BackLink } from "@/components/ui/BackLink";

interface AiSuggestion {
  suggestion_id: string;
  transaction: string;
  suggested_category_or_match: string;
  ai_score: number;
  ai_reasoning: string;
}

type FeedbackAction = "accept" | "reject" | "edit_accept";

export default function AiSuggestionsPage() {
  const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
  const [correctedValues, setCorrectedValues] = useState<
    Record<string, string>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiOperation("list_ai_suggestions_ai_suggestions_get");
      setSuggestions(data.items);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load AI suggestions",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSuggestions();
  }, [fetchSuggestions]);

  const submitFeedback = async (
    suggestion: AiSuggestion,
    action: FeedbackAction,
  ) => {
    const corrected = correctedValues[suggestion.suggestion_id]?.trim();
    await apiOperation("create_ai_feedback_ai_feedback_post", {
      body: {
        suggestion_id: suggestion.suggestion_id,
        action,
        ...(action === "edit_accept" && corrected
          ? { corrected_value: { value: corrected } }
          : {}),
      },
    });
  };

  const renderCorrectionInput = (
    suggestion: AiSuggestion,
    surface: "mobile" | "table",
  ) => {
    const inputId = `corrected-${surface}-${suggestion.suggestion_id}`;

    return (
      <>
        <label className="sr-only" htmlFor={inputId}>
          Corrected value
        </label>
        <input
          id={inputId}
          aria-label="Corrected value"
          className="input py-2 text-sm"
          value={correctedValues[suggestion.suggestion_id] ?? ""}
          onChange={(event) =>
            setCorrectedValues((current) => ({
              ...current,
              [suggestion.suggestion_id]: event.target.value,
            }))
          }
          placeholder="Optional correction"
        />
      </>
    );
  };

  const renderActionButtons = (suggestion: AiSuggestion, className = "") => (
    <div
      className={`grid grid-cols-2 gap-2 sm:flex sm:justify-end ${className}`}
    >
      <button
        type="button"
        className="btn-primary text-xs whitespace-nowrap"
        onClick={() => submitFeedback(suggestion, "accept")}
      >
        Accept
      </button>
      <button
        type="button"
        className="btn-secondary text-xs whitespace-nowrap"
        onClick={() => submitFeedback(suggestion, "reject")}
      >
        Reject
      </button>
      <button
        type="button"
        className="btn-secondary col-span-2 text-xs whitespace-nowrap"
        onClick={() => submitFeedback(suggestion, "edit_accept")}
      >
        Edit-then-Accept
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="p-4 md:p-6">
        <div className="card p-6 text-center text-muted md:p-8">
          Loading AI suggestions...
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6">
      <div className="mb-4">
        <BackLink>Back to Notifications</BackLink>
      </div>
      <div className="page-header">
        <h1 className="page-title">Suggestions to review</h1>
        <p className="page-description">
          Approve or correct the AI&apos;s suggested categories and matches that
          need a human eye.
        </p>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}

      <div className="card overflow-hidden">
        {suggestions.length === 0 ? (
          <div className="p-8 text-center text-muted">
            No pending AI suggestions
          </div>
        ) : (
          <>
            <div
              data-testid="ai-suggestions-mobile-list"
              className="divide-y divide-[var(--border)] md:hidden"
            >
              {suggestions.map((suggestion) => (
                <article
                  key={suggestion.suggestion_id}
                  data-testid={`ai-suggestion-mobile-card-${suggestion.suggestion_id}`}
                  className="space-y-4 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-medium uppercase text-muted">
                        Transaction
                      </p>
                      <p className="mt-1 break-words font-medium">
                        {suggestion.transaction}
                      </p>
                    </div>
                    <div className="flex-shrink-0 rounded-md bg-[var(--warning-muted)] px-2.5 py-1 text-sm font-semibold text-[var(--warning)]">
                      {suggestion.ai_score}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-3 text-sm">
                    <div>
                      <p className="text-xs font-medium uppercase text-muted">
                        Suggestion
                      </p>
                      <p className="mt-1 break-words">
                        {suggestion.suggested_category_or_match}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-medium uppercase text-muted">
                        Reasoning
                      </p>
                      <p className="mt-1 break-words text-muted">
                        {suggestion.ai_reasoning}
                      </p>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {renderCorrectionInput(suggestion, "mobile")}
                    {renderActionButtons(suggestion)}
                  </div>
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
                      <td className="px-4 py-3 font-medium">
                        {suggestion.transaction}
                      </td>
                      <td className="px-4 py-3">
                        {suggestion.suggested_category_or_match}
                      </td>
                      <td className="px-4 py-3 text-[var(--warning)] font-semibold">
                        {suggestion.ai_score}
                      </td>
                      <td className="px-4 py-3 text-muted">
                        {suggestion.ai_reasoning}
                      </td>
                      <td className="px-4 py-3 min-w-[220px]">
                        {renderCorrectionInput(suggestion, "table")}
                      </td>
                      <td className="px-4 py-3 min-w-[240px]">
                        {renderActionButtons(suggestion)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
