"use client";

import Link from "next/link";

import { useToast } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api-client";
import { useSettingsForm } from "@/hooks/useSettingsForm";
import type { UserAiSettings } from "@/lib/types";

const DEFAULT_SETTINGS: UserAiSettings = {
  enable_ai_reconciliation: false,
  enable_ai_classification: true,
  auto_accept_ai_suggestions: true,
};

export default function AiSettingsPanel() {
  const { showToast } = useToast();
  // `saved` is the last value persisted by the backend; `draft` is the
  // in-progress edit. A dirty form is any divergence between the two.
  const { draft, setDraft, loading, submitting, error, isDirty, submit, reset } = useSettingsForm<UserAiSettings>({
    load: () => apiOperation("get_current_user_settings_users_me_settings_get"),
    save: (next) => apiOperation("patch_current_user_settings_users_me_settings_patch", { body: next }),
    isEqual: (a, b) =>
      a.enable_ai_reconciliation === b.enable_ai_reconciliation &&
      a.enable_ai_classification === b.enable_ai_classification &&
      a.auto_accept_ai_suggestions === b.auto_accept_ai_suggestions,
    loadErrorMessage: "Failed to load AI settings",
    saveErrorMessage: "Failed to save AI settings",
  });

  const setField = (key: keyof UserAiSettings, value: boolean) => {
    setDraft((prev) => ({ ...(prev ?? DEFAULT_SETTINGS), [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const updated = await submit();
    if (updated !== null) showToast("AI settings saved", "success");
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
        <p className="page-description">Control AI-assisted reconciliation, classification and automatic acceptance.</p>
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
              <p className="text-sm text-muted">AI classifies each transaction. High-confidence results post without manual review. Turn this off to review every transaction yourself.</p>
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
          <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
            <div>
              <div className="font-medium">Auto-accept AI suggestions</div>
              <p className="text-sm text-muted">
                The system accepts the AI suggestion for each transaction, so a statement posts without a click. A row
                that the AI cannot place goes to a general account. These entries show a low confidence tier. Turn this
                off to approve the uncertain rows yourself. It needs AI classification.
              </p>
            </div>
            <input
              aria-label="Auto-accept AI suggestions"
              type="checkbox"
              checked={draft.auto_accept_ai_suggestions && draft.enable_ai_classification}
              disabled={submitting || !draft.enable_ai_classification}
              onChange={(event) => setField("auto_accept_ai_suggestions", event.target.checked)}
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
            onClick={reset}
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

export { AiSettingsPanel as AiSettingsPage };
