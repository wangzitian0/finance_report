import { useApiQuery } from "@/hooks/useApiQuery";

const DEFAULT_BASE_CURRENCY = "SGD";

export function useBaseCurrency(): { baseCurrency: string; loading: boolean } {
  const query = useApiQuery(["user-settings", "base-currency"], "get_base_currency_users_me_settings_base_currency_get", {});
  return { baseCurrency: query.data?.base_currency ?? DEFAULT_BASE_CURRENCY, loading: query.isLoading };
}
