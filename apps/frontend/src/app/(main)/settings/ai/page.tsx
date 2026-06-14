"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/ui/Toast";
import { fetchUserSettings, patchUserSettings } from "@/lib/api";
import type { UserAiSettings } from "@/lib/types";

const DEFAULT_SETTINGS: UserAiSettings = {
  enable_ai_reconciliation: false,
  enable_ai_classification: false,
};

export default function AiSettingsPage() {
  const { showToast } = useToast();
  // `saved` is the last value persisted by the backend; `draft` is the
  // in-progress edit. A dirty form is any divergence between the two.
  const [saved, setSaved] = useState<UserAiSettings | null>(null);
  const [draft, setDraft] = useState<UserAiSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchUserSettings();
      setSaved(data);
      setDraft(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load AI settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const isDirty = useMemo(() => {
    if (!saved || !draft) return false;
    return (
      saved.enable_ai_reconciliation !== draft.enable_ai_reconciliation ||
      saved.enable_ai_classification !== draft.enable_ai_classification
    );
  }, [saved, draft]);

  const setField = (key: keyof UserAiSettings, value: boolean) => {
    setDraft((prev) => ({ ...(prev ?? DEFAULT_SETTINGS), [key]: value }));
  };

  const handleReset = () => {
    if (saved) setDraft(saved);
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await patchUserSettings(draft);
      setSaved(updated);
      setDraft(updated);
      showToast("AI settings saved", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save AI settings");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">Loading AI settings...</div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="p-6 max-w-3xl">
        <div role="alert" className="alert-error">
          {error ?? "Failed to load AI settings"}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="page-header">
        <h1 className="page-title">AI Settings</h1>
        <p className="page-description">Control AI-assisted reconciliation and classification feature flags.</p>
      </div>

      <div className="mb-4">
        <Link href="/review/ai-suggestions" className="btn-secondary inline-flex text-sm">
          Review AI suggestions
        </Link>
      </div>

      {error && (
        <div role="alert" className="mb-4 alert-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="card divide-y divide-[var(--border)]">
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Enable AI reconciliation</div>
              <p className="text-sm text-muted">Use semantic AI scoring for reconciliation candidates in the 60-84 review band.</p>
            </div>
            <input
              aria-label="Enable AI reconciliation"
              type="checkbox"
              checked={draft.enable_ai_reconciliation}
              disabled={submitting}
              onChange={(event) => setField("enable_ai_reconciliation", event.target.checked)}
              className="h-5 w-5 rounded"
            />
          </label>
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Enable AI classification</div>
              <p className="text-sm text-muted">Use AI-extracted category suggestions before manual classification review.</p>
            </div>
            <input
              aria-label="Enable AI classification"
              type="checkbox"
              checked={draft.enable_ai_classification}
              disabled={submitting}
              onChange={(event) => setField("enable_ai_classification", event.target.checked)}
              className="h-5 w-5 rounded"
            />
          </label>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="btn-primary" disabled={!isDirty || submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleReset}
            disabled={!isDirty || submitting}
          >
            Reset
          </button>
          {isDirty && !submitting && (
            <span className="text-sm text-muted">Unsaved changes</span>
          )}
        </div>
      </form>
    </div>
  );
}
