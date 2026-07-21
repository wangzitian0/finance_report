import { useApiQuery } from "@/hooks/useApiQuery";

import type { BaseCurrency } from "@/lib/types";

// Sensible fallback while the effective base currency loads or if the request
// fails — never a hardcoded assumption baked into report queries (#1487).
const DEFAULT_BASE_CURRENCY = "SGD";

type UseBaseCurrencyResult = {
  baseCurrency: string;
  loading: boolean;
};

/** The user's effective base/reporting currency (ISO 4217), from app config. */
export function useBaseCurrency(): UseBaseCurrencyResult {
  const query = useApiQuery(
    ["app-config", "base-currency"],
    "get_base_currency_app_config_base_currency_get",
    {},
  );
  return {
    baseCurrency: query.data?.base_currency ?? DEFAULT_BASE_CURRENCY,
    loading: query.isLoading,
  };
}
