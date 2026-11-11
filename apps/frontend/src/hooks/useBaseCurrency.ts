import { useApiQuery } from "@/hooks/useApiQuery";

const DEFAULT_BASE_CURRENCY = "SGD";

export function useBaseCurrency(): { baseCurrency: string; loading: boolean } {
  const query = useApiQuery(["app-config", "base-currency"], "get_base_currency_app_config_base_currency_get", {});
  return { baseCurrency: query.data?.base_currency ?? DEFAULT_BASE_CURRENCY, loading: query.isLoading };
}
