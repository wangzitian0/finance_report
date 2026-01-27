"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

const DEFAULT_CURRENCIES = ["SGD", "USD", "EUR"];

export function useCurrencies() {
    const [currencies, setCurrencies] = useState<string[]>(DEFAULT_CURRENCIES);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        apiFetch<string[]>("/api/reports/currencies")
            .then((data) => {
                if (data && data.length > 0) {
                    setCurrencies(data);
                }
            })
            .catch(() => {
                // Fallback to defaults on error
            })
            .finally(() => setLoading(false));
    }, []);

    return { currencies, loading };
}
