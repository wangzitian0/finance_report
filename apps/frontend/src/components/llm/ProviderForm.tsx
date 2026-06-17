"use client";

import { useState } from "react";

import { createLlmProvider } from "@/lib/api";
import type { LlmProtocolFamily, LlmProviderResponse } from "@/lib/types";

/** Selectable protocol families with human-readable labels. */
export const PROTOCOL_OPTIONS: { value: LlmProtocolFamily; label: string }[] = [
  { value: "openrouter-compatible", label: "OpenRouter-compatible" },
  { value: "openai-compatible", label: "OpenAI-compatible" },
  { value: "anthropic-compatible", label: "Anthropic-compatible" },
];

/** Suggested base URL for the default OpenRouter free-tier protocol. */
export const OPENROUTER_API_BASE = "https://openrouter.ai/api/v1";

interface ProviderFormProps {
  /** Called with the created provider after a successful POST. */
  onCreated: (provider: LlmProviderResponse) => void;
  /** Optional cancel affordance (e.g. modal dismiss). */
  onCancel?: () => void;
  /** Label for the submit button. */
  submitLabel?: string;
}

/**
 * Shared form to create an LLM provider (EPIC-023 PR4).
 *
 * Defaults to the OpenRouter-compatible protocol with its free-tier base URL
 * pre-filled, so a first-run user can paste a key and reach `:free` models
 * without extra configuration. The API key is a password input and is only
 * ever sent (write-only); it is never read back from the backend.
 */
export function ProviderForm({
  onCreated,
  onCancel,
  submitLabel = "Add provider",
}: ProviderFormProps) {
  const [protocol, setProtocol] = useState<LlmProtocolFamily>(
    "openrouter-compatible"
  );
  const [apiBase, setApiBase] = useState(OPENROUTER_API_BASE);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createLlmProvider({
        label: label.trim(),
        protocol,
        api_key: apiKey,
        api_base: apiBase.trim() ? apiBase.trim() : null,
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add provider");
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = label.trim().length > 0 && apiKey.length > 0 && !submitting;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className="alert-error">
          {error}
        </div>
      )}

      <div>
        <label htmlFor="provider-protocol" className="block text-sm font-medium mb-1">
          Protocol family
        </label>
        <select
          id="provider-protocol"
          className="input w-full"
          value={protocol}
          disabled={submitting}
          onChange={(event) =>
            setProtocol(event.target.value as LlmProtocolFamily)
          }
        >
          {PROTOCOL_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="provider-api-base" className="block text-sm font-medium mb-1">
          API base URL
        </label>
        <input
          id="provider-api-base"
          type="text"
          className="input w-full"
          value={apiBase}
          disabled={submitting}
          placeholder={OPENROUTER_API_BASE}
          onChange={(event) => setApiBase(event.target.value)}
        />
        <p className="mt-1 text-xs text-muted">
          Optional. OpenRouter free-tier <code>:free</code> models are available
          at {OPENROUTER_API_BASE}.
        </p>
      </div>

      <div>
        <label htmlFor="provider-label" className="block text-sm font-medium mb-1">
          Label
        </label>
        <input
          id="provider-label"
          type="text"
          className="input w-full"
          value={label}
          disabled={submitting}
          placeholder="My OpenRouter key"
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>

      <div>
        <label htmlFor="provider-api-key" className="block text-sm font-medium mb-1">
          API key
        </label>
        <input
          id="provider-api-key"
          type="password"
          className="input w-full"
          value={apiKey}
          disabled={submitting}
          autoComplete="off"
          onChange={(event) => setApiKey(event.target.value)}
        />
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button type="submit" className="btn-primary" disabled={!canSubmit}>
          {submitting ? "Saving..." : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            className="btn-secondary"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
