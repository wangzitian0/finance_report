"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchLlmConfigStatus } from "@/lib/api";
import { getUserId } from "@/lib/auth";

export interface UseLlmConfigStatus {
  /** Whether the user has a usable LLM configuration; null until first load. */
  configured: boolean | null;
  /** True while a status fetch is in flight. */
  loading: boolean;
  /** Re-fetch the configuration status (e.g. after creating a provider). */
  refresh: () => Promise<void>;
}

/**
 * LLM first-run status (EPIC-023 PR4).
 *
 * Fetches `GET /api/llm/config/status` on mount and exposes the configured
 * flag plus a manual `refresh`. Only runs when a local session id is present,
 * mirroring `useSessionBootstrap` — the status endpoint is authenticated and
 * the login route renders outside the authenticated shell.
 */
export function useLlmConfigStatus(): UseLlmConfigStatus {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (getUserId() === null) return;
    setLoading(true);
    try {
      const status = await fetchLlmConfigStatus();
      setConfigured(status.configured);
    } catch {
      // A 401 redirects via apiFetch. For any other failure, leave the flag
      // untouched rather than forcing the first-run modal on a transient error.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { configured, loading, refresh };
}
