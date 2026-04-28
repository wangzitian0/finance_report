"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

interface AiSuggestion {
  suggestion_id: string;
  transaction: string;
  suggested_category_or_match: string;
  ai_score: number;
  ai_reasoning: string;
}

export default function AiSuggestionsPage() {
  const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
  const [correctedValues, setCorrectedValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ items: AiSuggestion[] }>("/api/ai/suggestions");
      setSuggestions(data.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load AI suggestions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSuggestions();
  }, [fetchSuggestions]);

  const submitFeedback = async (suggestion: AiSuggestion, action: "accept" | "reject" | "edit_accept") => {
    const corrected = correctedValues[suggestion.suggestion_id]?.trim();
    await apiFetch("/api/ai/feedback", {
      method: "POST",
      body: JSON.stringify({
        suggestion_id: suggestion.suggestion_id,
        action,
        ...(action === "edit_accept" && corrected ? { corrected_value: { value: corrected } } : {}),
      }),
    });
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">Loading AI suggestions...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="page-header">
        <h1 className="page-title">AI Suggestion Review Queue</h1>
        <p className="page-description">Review AI classifications and reconciliation matches in the 60-84 score band.</p>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}

      <div className="card overflow-hidden">
        {suggestions.length === 0 ? (
          <div className="p-8 text-center text-muted">No pending AI suggestions</div>
        ) : (
          <table className="w-full text-sm">
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
                  <td className="px-4 py-3">
                    <label className="sr-only" htmlFor={`corrected-${suggestion.suggestion_id}`}>Corrected value</label>
                    <input
                      id={`corrected-${suggestion.suggestion_id}`}
                      aria-label="Corrected value"
                      className="input py-1 text-sm"
                      value={correctedValues[suggestion.suggestion_id] ?? ""}
                      onChange={(event) =>
                        setCorrectedValues((current) => ({
                          ...current,
                          [suggestion.suggestion_id]: event.target.value,
                        }))
                      }
                      placeholder="Optional correction"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <button type="button" className="btn-primary text-xs" onClick={() => submitFeedback(suggestion, "accept")}>
                        Accept
                      </button>
                      <button type="button" className="btn-secondary text-xs" onClick={() => submitFeedback(suggestion, "reject")}>
                        Reject
                      </button>
                      <button type="button" className="btn-secondary text-xs" onClick={() => submitFeedback(suggestion, "edit_accept")}>
                        Edit-then-Accept
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
