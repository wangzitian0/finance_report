import { useApiQuery } from "@/hooks/useApiQuery";

const DEFAULT_CURRENCIES = ["SGD", "USD", "EUR"];

type UseCurrenciesResult = {
  currencies: string[];
  loading: boolean;
};

export function useCurrencies(): UseCurrenciesResult {
  const query = useApiQuery(
    ["report-currencies"],
    "get_available_currencies_reports_currencies_get",
    {},
  );
  const currencies = query.data?.length ? query.data : DEFAULT_CURRENCIES;

  return { currencies, loading: query.isLoading };
}
