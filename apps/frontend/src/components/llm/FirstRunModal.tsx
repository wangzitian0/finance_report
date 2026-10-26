"use client";

import { useState } from "react";

import DetailDialog from "@/components/ui/DetailDialog";
import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";
import { apiOperation } from "@/lib/api-client";
import type { LlmProtocolFamily, LlmProviderResponse } from "@/lib/types";

export const PROTOCOL_OPTIONS: { value: LlmProtocolFamily; label: string }[] = [
  { value: "openrouter-compatible", label: "OpenRouter-compatible" },
  { value: "openai-compatible", label: "OpenAI-compatible" },
  { value: "anthropic-compatible", label: "Anthropic-compatible" },
];

export const OPENROUTER_API_BASE = "https://openrouter.ai/api/v1";

interface ProviderFormProps {
  onCreated: (provider: LlmProviderResponse) => void;
  onCancel?: () => void;
  submitLabel?: string;
}

export function ProviderForm({ onCreated, onCancel, submitLabel = "Add provider" }: ProviderFormProps) {
  const [protocol, setProtocol] = useState<LlmProtocolFamily>("openrouter-compatible");
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
      const created = await apiOperation("create_provider_llm_providers_post", {
        body: { label: label.trim(), protocol, api_key: apiKey, api_base: apiBase.trim() ? apiBase.trim() : null },
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
      {error && <div role="alert" className="alert-error">{error}</div>}
      <div>
        <label htmlFor="provider-protocol" className="block text-sm font-medium mb-1">Protocol family</label>
        <select
          id="provider-protocol"
          className="input w-full"
          value={protocol}
          disabled={submitting}
          onChange={(e) => setProtocol(e.target.value as LlmProtocolFamily)}
        >
          {PROTOCOL_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="provider-api-base" className="block text-sm font-medium mb-1">API base URL</label>
        <input
          id="provider-api-base"
          type="text"
          className="input w-full"
          value={apiBase}
          disabled={submitting}
          placeholder={OPENROUTER_API_BASE}
          onChange={(e) => setApiBase(e.target.value)}
        />
        <p className="mt-1 text-xs text-muted">
          Optional. OpenRouter free-tier <code>:free</code> models are available at {OPENROUTER_API_BASE}.
        </p>
      </div>
      <div>
        <label htmlFor="provider-label" className="block text-sm font-medium mb-1">Label</label>
        <input
          id="provider-label"
          type="text"
          className="input w-full"
          value={label}
          disabled={submitting}
          placeholder="My OpenRouter key"
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      <div>
        <label htmlFor="provider-api-key" className="block text-sm font-medium mb-1">API key</label>
        <input
          id="provider-api-key"
          type="password"
          className="input w-full"
          value={apiKey}
          disabled={submitting}
          autoComplete="off"
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button type="submit" className="btn-primary" disabled={!canSubmit}>
          {submitting ? "Saving..." : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
        )}
      </div>
    </form>
  );
}

export function FirstRunModal() {
  const { configured, refresh } = useLlmConfigStatus();
  const [dismissed, setDismissed] = useState(false);
  const isOpen = configured === false && !dismissed;
  if (!isOpen) return null;

  return (
    <DetailDialog isOpen={isOpen} onClose={() => setDismissed(true)} title="Set up your AI provider">
      <p className="mb-4 text-sm text-muted">
        Connect an LLM provider to enable AI extraction, summaries, and the advisor. OpenRouter offers free <code>:free</code> models to get started.
      </p>
      <ProviderForm submitLabel="Save provider" onCancel={() => setDismissed(true)} onCreated={() => { void refresh(); }} />
    </DetailDialog>
  );
}
