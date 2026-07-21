import {
  useQuery,
  type UseQueryOptions,
  type QueryKey,
} from "@tanstack/react-query";

import {
  apiOperation,
  type ApiOperationRequest,
  type ApiOperationResponse,
} from "@/lib/api-client";
import type { ApiOperationId } from "@/lib/api-operations";

type ApiQueryOptions<TQueryData, TData = TQueryData> = Omit<
  UseQueryOptions<TQueryData, Error, TData, QueryKey>,
  "queryKey" | "queryFn"
>;

export function useApiQuery<
  Id extends ApiOperationId,
  TData = ApiOperationResponse<Id>,
>(
  queryKey: QueryKey,
  operationId: Id,
  request: ApiOperationRequest<Id>,
  options: ApiQueryOptions<ApiOperationResponse<Id>, TData> = {},
) {
  return useQuery<ApiOperationResponse<Id>, Error, TData>({
    queryKey,
    queryFn: () => apiOperation(operationId, request),
    ...options,
  });
}
