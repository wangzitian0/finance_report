import { useQuery, type UseQueryOptions, type QueryKey } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

type ApiQueryOptions<TData> = Omit<
  UseQueryOptions<TData, Error, TData, QueryKey>,
  "queryKey" | "queryFn"
>;

export function useApiQuery<TData>(
  queryKey: QueryKey,
  path: string,
  options: ApiQueryOptions<TData> = {},
) {
  return useQuery<TData, Error>({
    queryKey,
    queryFn: () => apiFetch<TData>(path),
    ...options,
  });
}
