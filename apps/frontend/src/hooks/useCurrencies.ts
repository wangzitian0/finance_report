"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

const DEFAULT_CURRENCIES = ["SGD", "USD", "EUR"];

type UseCurrenciesResult = {
    currencies: string[];
    loading: boolean;
};

export function useCurrencies(): UseCurrenciesResult {
    const [currencies, setCurrencies] = useState<string[]>(DEFAULT_CURRENCIES);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        apiFetch<string[]>("/api/reports/currencies")
            .then((data) => {
                if (data && data.length > 0) {
                    setCurrencies(data);
                }
            })
            .catch((error) => {
                console.error("[useCurrencies] Failed to load currencies", error);
            })
            .finally(() => setLoading(false));
    }, []);

    return { currencies, loading };
}
