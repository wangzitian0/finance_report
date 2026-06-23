"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui/Toast";
import { fetchBaseCurrency, updateBaseCurrency } from "@/lib/api";

// EPIC-012 AC12.39 / #1340: edit the effective base reporting currency.
// The backend validates the ISO 4217 code (HTTP 422 on invalid), so this
// control stays minimal — a text input normalized to upper-case.
export default function GeneralSettingsPage() {
  const { showToast } = useToast();
  const [saved, setSaved] = useState<string | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadBaseCurrency = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBaseCurrency();
      setSaved(data.base_currency);
      setDraft(data.base_currency);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load base currency");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBaseCurrency();
  }, [loadBaseCurrency]);

  const isDirty = useMemo(() => saved !== null && draft !== saved, [saved, draft]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting || !isDirty) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await updateBaseCurrency(draft);
      setSaved(updated.base_currency);
      setDraft(updated.base_currency);
      showToast("Base currency saved", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save base currency");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">Loading general settings...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="page-header">
        <h1 className="page-title">General Settings</h1>
        <p className="page-description">App-level settings shared across reports.</p>
      </div>

      {error && (
        <div role="alert" className="mb-4 alert-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="card p-5">
          <label htmlFor="base-currency" className="block font-medium">
            Base currency
          </label>
          <p className="text-sm text-muted">
            The reporting currency all statements consolidate into (ISO 4217, e.g. SGD, USD, EUR).
          </p>
          <input
            id="base-currency"
            aria-label="Base currency"
            type="text"
            value={draft}
            disabled={submitting}
            maxLength={3}
            onChange={(event) => setDraft(event.target.value.toUpperCase())}
            className="input mt-3 w-32 uppercase"
          />
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!isDirty || submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              if (saved !== null) setDraft(saved);
              setError(null);
            }}
            disabled={!isDirty || submitting}
          >
            Reset
          </button>
          {isDirty && !submitting && <span className="text-sm text-muted">Unsaved changes</span>}
        </div>
      </form>
    </div>
  );
}
