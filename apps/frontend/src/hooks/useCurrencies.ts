import { useApiQuery } from "@/hooks/useApiQuery";

const DEFAULT_CURRENCIES = ["SGD", "USD", "EUR"];

export function useCurrencies(): { currencies: string[]; loading: boolean } {
  const query = useApiQuery(["report-currencies"], "get_available_currencies_reports_currencies_get", {});
  return { currencies: query.data?.length ? query.data : DEFAULT_CURRENCIES, loading: query.isLoading };
}
