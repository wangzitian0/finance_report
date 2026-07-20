"use client";

import { useApiQuery } from "@/hooks/useApiQuery";
import { getUserId } from "@/lib/auth";
import type { LlmConfigStatusResponse } from "@/lib/types";

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
 * `GET /api/llm/config/status` via `useApiQuery` (#1868 S5 PR-C — was the
 * pre-react-query useState/useEffect idiom). Only runs when a local session
 * id is present, mirroring `useSessionBootstrap` — the status endpoint is
 * authenticated and the login route renders outside the authenticated shell.
 * A failed fetch leaves `configured` at its last-known value (react-query's
 * `data` is untouched by a query error) rather than forcing the first-run
 * modal on a transient error.
 */
export function useLlmConfigStatus(): UseLlmConfigStatus {
  const query = useApiQuery(
    ["llm", "config-status"],
    "get_config_status_llm_config_status_get",
    {},
    { enabled: getUserId() !== null },
  );

  return {
    configured: query.data?.configured ?? null,
    loading: query.isFetching,
    refresh: async () => {
      await query.refetch();
    },
  };
}
