"use client";

import { useApiQuery } from "@/hooks/useApiQuery";
import { getUserId } from "@/lib/auth";

export interface UseLlmConfigStatus {
  configured: boolean | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

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
