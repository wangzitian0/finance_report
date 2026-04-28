"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

interface AiSettings {
  enable_ai_reconciliation: boolean;
  enable_ai_classification: boolean;
}

export default function AiSettingsPage() {
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<AiSettings>("/api/users/me/settings");
      setSettings(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load AI settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const updateSetting = async (key: keyof AiSettings, value: boolean) => {
    const nextSettings = { ...(settings ?? { enable_ai_reconciliation: false, enable_ai_classification: false }), [key]: value };
    setSettings(nextSettings);
    try {
      const updated = await apiFetch<AiSettings>("/api/users/me/settings", {
        method: "PATCH",
        body: JSON.stringify({ [key]: value }),
      });
      setSettings(updated);
      setError(null);
    } catch (err) {
      setSettings(settings);
      setError(err instanceof Error ? err.message : "Failed to update AI settings");
    }
  };

  if (loading || !settings) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center text-muted">Loading AI settings...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="page-header">
        <h1 className="page-title">AI Settings</h1>
        <p className="page-description">Control AI-assisted reconciliation and classification feature flags.</p>
      </div>

      {error && <div className="mb-4 alert-error">{error}</div>}

      <div className="card divide-y divide-[var(--border)]">
        <label className="p-5 flex items-center justify-between gap-4 cursor-pointer">
          <div>
            <div className="font-medium">Enable AI reconciliation</div>
            <p className="text-sm text-muted">Use semantic AI scoring for reconciliation candidates in the 60-84 review band.</p>
          </div>
          <input
            aria-label="Enable AI reconciliation"
            type="checkbox"
            checked={settings.enable_ai_reconciliation}
            onChange={(event) => updateSetting("enable_ai_reconciliation", event.target.checked)}
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
            checked={settings.enable_ai_classification}
            onChange={(event) => updateSetting("enable_ai_classification", event.target.checked)}
            className="h-5 w-5 rounded"
          />
        </label>
      </div>
    </div>
  );
}
