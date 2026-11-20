import {
  apiOperation,
  type ApiOperationArgs,
  type ApiOperationRequest,
  type ApiOperationResponse,
} from "@/lib/api";
import type { ApiOperationId } from "@/lib/api-operations";

/** The `maximum` of the shared `limit` query parameter (the backend `MAX_PAGE_LIMIT` in `src/deps.py`). */
export const MAX_PAGE_LIMIT = 500;
/** The helper stops with an error after this many pages (100,000 rows), so a server that ignores `offset` cannot loop it. */
export const MAX_PAGES = 200;

type PageResponse = { items?: unknown[]; total?: number };
type PagedQuery = { query?: { limit?: number | null; offset?: number | null } | null };

/** An operation that takes `limit`/`offset` and returns `items`. */
export type PagedOperationId = {
  [Id in ApiOperationId]: ApiOperationResponse<Id> extends { items: unknown[] }
    ? ApiOperationRequest<Id> extends PagedQuery
      ? Id
      : never
    : never;
}[ApiOperationId];

/**
 * Read every page of a paginated list operation and return one response that holds all items.
 * Use it where the screen needs the full list; the server returns `DEFAULT_PAGE_LIMIT` rows otherwise.
 */
export async function apiOperationAllPages<Id extends PagedOperationId>(
  operationId: Id,
  ...args: ApiOperationArgs<Id>
): Promise<ApiOperationResponse<Id>> {
  const request = (args[0] ?? {}) as ApiOperationRequest<Id> & { query?: Record<string, unknown> | null };
  const items: unknown[] = [];
  for (let pageIndex = 0; pageIndex < MAX_PAGES; pageIndex += 1) {
    const offset = pageIndex * MAX_PAGE_LIMIT;
    const pageRequest = { ...request, query: { ...(request.query ?? {}), limit: MAX_PAGE_LIMIT, offset } };
    const page = (await apiOperation(operationId, ...([pageRequest] as unknown as ApiOperationArgs<Id>))) as PageResponse;
    const pageItems = page.items ?? [];
    items.push(...pageItems);
    const reachedTotal = page.total !== undefined && items.length >= page.total;
    if (pageItems.length < MAX_PAGE_LIMIT || reachedTotal) {
      return { ...page, items } as ApiOperationResponse<Id>;
    }
  }
  throw new Error(`${operationId} returned more than ${MAX_PAGES} full pages`);
}
