import { useApiQuery } from "@/hooks/useApiQuery";

const DEFAULT_CURRENCIES = ["SGD", "USD", "EUR"];

type UseCurrenciesResult = {
    currencies: string[];
    loading: boolean;
};

export function useCurrencies(): UseCurrenciesResult {
    const query = useApiQuery<string[]>(["report-currencies"], "/api/reports/currencies");
    const currencies = query.data?.length ? query.data : DEFAULT_CURRENCIES;

    return { currencies, loading: query.isLoading };
}
