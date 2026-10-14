"use client";

import Link from "next/link";

import { useToast } from "@/components/ui/Toast";
import { apiOperation } from "@/lib/api-client";
import { useSettingsForm } from "@/hooks/useSettingsForm";
import type { UserAiSettings, UserAiSettingsUpdate } from "@/lib/types";

const DEFAULT_SETTINGS: UserAiSettings = {
  enable_ai_reconciliation: false,
  enable_ai_classification: true,
  auto_accept_ai_suggestions: true,
  auto_accept_ai_suggestions_active: true,
};

const CHOICES = ["enable_ai_reconciliation", "enable_ai_classification", "auto_accept_ai_suggestions"] as const;

/**
 * The choices that the user changed. A save stores nothing that the user did not edit, so a default that
 * the product changes later still reaches a user who never chose a value. `auto_accept_ai_suggestions_active`
 * is read-only: it shows what the system uses.
 */
export function changedChoices(saved: UserAiSettings | null, next: UserAiSettings): UserAiSettingsUpdate {
  const body: UserAiSettingsUpdate = {};
  for (const key of CHOICES) {
    if (saved === null || saved[key] !== next[key]) body[key] = next[key];
  }
  return body;
}

export default function AiSettingsPanel() {
  const { showToast } = useToast();
  // `saved` is the last value persisted by the backend; `draft` is the
  // in-progress edit. A dirty form is any divergence between the two.
  const { saved, draft, setDraft, loading, submitting, error, isDirty, submit, reset } = useSettingsForm<UserAiSettings>({
    load: () => apiOperation("get_current_user_settings_users_me_settings_get"),
    save: (next, previous) =>
      apiOperation("patch_current_user_settings_users_me_settings_patch", { body: changedChoices(previous, next) }),
    isEqual: (a, b) => CHOICES.every((key) => a[key] === b[key]),
    loadErrorMessage: "Failed to load AI settings",
    saveErrorMessage: "Failed to save AI settings",
  });

  // The operator can turn the automatic acceptance off for all accounts. The saved choice then stays on,
  // and the system does not use it. The note tells the user why the switch has no effect.
  const operatorTurnedItOff =
    saved !== null &&
    saved.enable_ai_classification &&
    saved.auto_accept_ai_suggestions &&
    !saved.auto_accept_ai_suggestions_active;

  const setField = (key: (typeof CHOICES)[number], value: boolean) => {
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
              {operatorTurnedItOff && (
                <p role="note" className="text-sm text-muted mt-1">
                  The operator of this server turned the automatic acceptance off for all accounts. Your choice
                  applies again when the operator turns it on.
                </p>
              )}
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
