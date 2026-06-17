"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ProviderForm } from "@/components/llm/ProviderForm";
import { useToast } from "@/components/ui/Toast";
import {
  deleteLlmProvider,
  fetchLlmCatalog,
  fetchLlmProviders,
  fetchLlmScenes,
  putLlmScenes,
} from "@/lib/api";
import type {
  LlmModelResponse,
  LlmProviderResponse,
  LlmReasoningEffort,
  LlmScene,
  LlmSceneBindingItem,
} from "@/lib/types";

/** The five scenes the user can bind, with friendly labels. */
const SCENES: { scene: LlmScene; label: string; description: string }[] = [
  { scene: "extraction.ocr", label: "Extraction · OCR", description: "Read text from scanned documents." },
  { scene: "extraction.vision", label: "Extraction · Vision", description: "Understand statement layouts and tables." },
  { scene: "extraction.json", label: "Extraction · JSON", description: "Produce structured records from raw text." },
  { scene: "advisor.chat", label: "Advisor · Chat", description: "Answer grounded financial questions." },
  { scene: "statement.summary", label: "Statement · Summary", description: "Summarise an imported statement." },
];

const REASONING_OPTIONS: LlmReasoningEffort[] = ["none", "low", "medium", "high"];

/** A binding whose provider is unset (empty string) signals "not configured". */
function emptyBinding(scene: LlmScene): LlmSceneBindingItem {
  return {
    scene,
    provider_id: "",
    model: "",
    reasoning: "none",
    prefer_free: false,
    fallback_model_ids: [],
    max_tokens: null,
  };
}

/** Serialize bindings to a stable string for dirty-checking. */
function serialize(bindings: LlmSceneBindingItem[]): string {
  return JSON.stringify(
    [...bindings].sort((a, b) => a.scene.localeCompare(b.scene))
  );
}

export default function LlmSettingsPage() {
  const { showToast } = useToast();

  const [providers, setProviders] = useState<LlmProviderResponse[]>([]);
  const [catalog, setCatalog] = useState<LlmModelResponse[]>([]);
  const [saved, setSaved] = useState<LlmSceneBindingItem[] | null>(null);
  const [draft, setDraft] = useState<LlmSceneBindingItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showProviderForm, setShowProviderForm] = useState(false);

  // Merge backend bindings with the fixed scene list so every scene has a row.
  const mergeBindings = useCallback(
    (bindings: LlmSceneBindingItem[]): LlmSceneBindingItem[] =>
      SCENES.map(({ scene }) => {
        const existing = bindings.find((b) => b.scene === scene);
        return existing ?? emptyBinding(scene);
      }),
    []
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [providerList, sceneList, catalogResponse] = await Promise.all([
        fetchLlmProviders(),
        fetchLlmScenes(),
        fetchLlmCatalog(),
      ]);
      setProviders(providerList.providers);
      setCatalog(catalogResponse.models);
      const merged = mergeBindings(sceneList.bindings);
      setSaved(merged);
      setDraft(merged);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load LLM settings");
    } finally {
      setLoading(false);
    }
  }, [mergeBindings]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const isDirty = useMemo(() => {
    if (!saved || !draft) return false;
    return serialize(saved) !== serialize(draft);
  }, [saved, draft]);

  const updateBinding = (
    scene: LlmScene,
    patch: Partial<LlmSceneBindingItem>
  ) => {
    setDraft((prev) =>
      (prev ?? []).map((b) => (b.scene === scene ? { ...b, ...patch } : b))
    );
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft || submitting) return;
    // Only persist bindings the user actually configured (provider + model).
    const configured = draft.filter(
      (b) => b.provider_id !== "" && b.model.trim() !== ""
    );
    setSubmitting(true);
    setError(null);
    try {
      const response = await putLlmScenes({ bindings: configured });
      const merged = mergeBindings(response.bindings);
      setSaved(merged);
      setDraft(merged);
      showToast("LLM bindings saved", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save LLM bindings");
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = () => {
    if (saved) setDraft(saved);
    setError(null);
  };

  const handleDeleteProvider = async (id: string) => {
    setError(null);
    try {
      await deleteLlmProvider(id);
      showToast("Provider deleted", "success");
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete provider");
    }
  };

  const handleProviderCreated = async () => {
    setShowProviderForm(false);
    showToast("Provider added", "success");
    await loadAll();
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">Loading LLM settings...</div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="p-6 max-w-3xl">
        <div role="alert" className="alert-error">
          {error ?? "Failed to load LLM settings"}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="page-header">
        <h1 className="page-title">LLM Models</h1>
        <p className="page-description">
          Configure providers and bind each AI scene to a model.
        </p>
      </div>

      {error && (
        <div role="alert" className="mb-4 alert-error">
          {error}
        </div>
      )}

      {/* Providers */}
      <section className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Providers</h2>
          <button
            type="button"
            className="btn-secondary text-sm"
            onClick={() => setShowProviderForm((v) => !v)}
          >
            {showProviderForm ? "Close" : "Add provider"}
          </button>
        </div>

        {showProviderForm && (
          <div className="card p-5 mb-4">
            <ProviderForm
              onCreated={handleProviderCreated}
              onCancel={() => setShowProviderForm(false)}
            />
          </div>
        )}

        {providers.length === 0 ? (
          <div className="card p-5 text-sm text-muted">
            No providers configured yet. Add one to bind scenes to models.
          </div>
        ) : (
          <ul className="card divide-y divide-[var(--border)]">
            {providers.map((provider) => (
              <li key={provider.id} className="p-4 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="font-medium truncate">{provider.label}</div>
                  <div className="text-xs text-muted">
                    {provider.protocol}
                    {provider.api_base ? ` · ${provider.api_base}` : ""}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  aria-label={`Delete provider ${provider.label}`}
                  onClick={() => handleDeleteProvider(provider.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Scene bindings */}
      <form onSubmit={handleSubmit}>
        <h2 className="mb-3 text-lg font-semibold">Scene bindings</h2>
        <div className="space-y-4">
          {SCENES.map(({ scene, label, description }) => {
            const binding = draft.find((b) => b.scene === scene)!;
            const sceneModels = catalog.filter(
              (m) => m.provider_id === binding.provider_id
            );
            const listId = `models-${scene.replace(/\./g, "-")}`;
            return (
              <div key={scene} className="card p-5 space-y-3">
                <div>
                  <div className="font-medium">{label}</div>
                  <p className="text-sm text-muted">{description}</p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor={`provider-${scene}`}
                      className="block text-sm font-medium mb-1"
                    >
                      Provider
                    </label>
                    <select
                      id={`provider-${scene}`}
                      className="input w-full"
                      value={binding.provider_id}
                      disabled={submitting}
                      onChange={(event) =>
                        updateBinding(scene, { provider_id: event.target.value })
                      }
                    >
                      <option value="">— Not configured —</option>
                      {providers.map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label
                      htmlFor={`model-${scene}`}
                      className="block text-sm font-medium mb-1"
                    >
                      Model
                    </label>
                    <input
                      id={`model-${scene}`}
                      type="text"
                      className="input w-full"
                      list={listId}
                      value={binding.model}
                      disabled={submitting}
                      placeholder="e.g. openrouter/auto"
                      onChange={(event) =>
                        updateBinding(scene, { model: event.target.value })
                      }
                    />
                    <datalist id={listId}>
                      {sceneModels.map((model) => (
                        <option key={model.id} value={model.id} />
                      ))}
                    </datalist>
                  </div>

                  <div>
                    <label
                      htmlFor={`reasoning-${scene}`}
                      className="block text-sm font-medium mb-1"
                    >
                      Reasoning depth
                    </label>
                    <select
                      id={`reasoning-${scene}`}
                      className="input w-full"
                      value={binding.reasoning}
                      disabled={submitting}
                      onChange={(event) =>
                        updateBinding(scene, {
                          reasoning: event.target.value as LlmReasoningEffort,
                        })
                      }
                    >
                      {REASONING_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label
                      htmlFor={`fallbacks-${scene}`}
                      className="block text-sm font-medium mb-1"
                    >
                      Fallback models (comma-separated)
                    </label>
                    <input
                      id={`fallbacks-${scene}`}
                      type="text"
                      className="input w-full"
                      value={(binding.fallback_model_ids ?? []).join(", ")}
                      disabled={submitting}
                      placeholder="model-a, model-b"
                      onChange={(event) =>
                        updateBinding(scene, {
                          fallback_model_ids: event.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter((s) => s.length > 0),
                        })
                      }
                    />
                  </div>
                </div>

                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded"
                    checked={binding.prefer_free}
                    disabled={submitting}
                    aria-label={`Prefer free models for ${label}`}
                    onChange={(event) =>
                      updateBinding(scene, { prefer_free: event.target.checked })
                    }
                  />
                  Prefer free models
                </label>
              </div>
            );
          })}
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
