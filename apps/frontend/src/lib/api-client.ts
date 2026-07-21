import * as api from "./api";
import { API_OPERATIONS, type ApiOperationId } from "./api-operations";

export type {
  ApiOperationArgs,
  ApiOperationRequest,
  ApiOperationResponse,
  ApiOperationUploadRequest,
  MultipartOperationId,
} from "./api";
export { ApiError } from "./api";

type OperationRequest = {
  path?: Record<string, unknown>;
  query?: object;
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
};

const useProductionOperationClient = process.env.NODE_ENV !== "test";

function compatibilityPath(
  operationId: ApiOperationId,
  request: OperationRequest,
): string {
  const definition = API_OPERATIONS[operationId];
  let path = definition.path.replace(
    /\{([^}]+)\}/g,
    (_placeholder, name: string) => {
      const value = request.path?.[name];
      if (value === undefined || value === null) {
        throw new Error(`Missing OpenAPI path parameter: ${name}`);
      }
      return encodeURIComponent(String(value));
    },
  );
  if (request.query) {
    const query = new URLSearchParams();
    for (const [name, rawValue] of Object.entries(request.query)) {
      if (rawValue === undefined || rawValue === null) continue;
      for (const value of Array.isArray(rawValue) ? rawValue : [rawValue]) {
        query.append(name, String(value));
      }
    }
    const encoded = query.toString();
    if (encoded) path = `${path}?${encoded}`;
  }
  return path;
}

export async function apiOperation<Id extends ApiOperationId>(
  operationId: Id,
  ...args: api.ApiOperationArgs<Id>
): Promise<api.ApiOperationResponse<Id>> {
  const request = (args[0] ?? {}) as api.ApiOperationRequest<Id>;
  if (useProductionOperationClient && "apiOperation" in api) {
    return api.apiOperation(operationId, ...args);
  }
  const parts = request as OperationRequest;
  const path = compatibilityPath(operationId, parts);
  if (
    API_OPERATIONS[operationId].method === "DELETE" &&
    parts.body === undefined &&
    parts.headers === undefined &&
    parts.signal === undefined
  ) {
    if (Reflect.has(api, "apiDelete")) {
      const legacyApiDelete = Reflect.get(api, "apiDelete") as typeof api.apiDelete;
      await legacyApiDelete(path);
    } else {
      await api.apiFetch(path, { method: "DELETE" });
    }
    return undefined as api.ApiOperationResponse<Id>;
  }
  if (
    API_OPERATIONS[operationId].method === "GET" &&
    parts.body === undefined &&
    parts.headers === undefined &&
    parts.signal === undefined
  ) {
    return api.apiFetch(path);
  }
  return api.apiFetch(path, {
    method: API_OPERATIONS[operationId].method,
    body: parts.body === undefined ? undefined : JSON.stringify(parts.body),
    headers: parts.headers,
    signal: parts.signal,
  });
}

export async function apiOperationStream<Id extends ApiOperationId>(
  operationId: Id,
  request: api.ApiOperationRequest<Id>,
): Promise<api.StreamResponse> {
  if (useProductionOperationClient && "apiOperationStream" in api) {
    return api.apiOperationStream(operationId, request);
  }
  const parts = request as OperationRequest;
  return api.apiStream(compatibilityPath(operationId, parts), {
    method: API_OPERATIONS[operationId].method,
    body: parts.body === undefined ? undefined : JSON.stringify(parts.body),
    headers: parts.headers,
    signal: parts.signal,
  });
}

export async function apiOperationDownload<Id extends ApiOperationId>(
  operationId: Id,
  request: api.ApiOperationRequest<Id>,
): Promise<api.DownloadResponse> {
  if (useProductionOperationClient && "apiOperationDownload" in api) {
    return api.apiOperationDownload(operationId, request);
  }
  const parts = request as OperationRequest;
  const path = compatibilityPath(operationId, parts);
  if (
    API_OPERATIONS[operationId].method === "GET" &&
    parts.headers === undefined &&
    parts.signal === undefined
  ) {
    return api.apiDownload(path);
  }
  return api.apiDownload(path, {
    method: API_OPERATIONS[operationId].method,
    headers: parts.headers,
    signal: parts.signal,
  });
}

export async function apiOperationUpload<Id extends api.MultipartOperationId>(
  operationId: Id,
  request: api.ApiOperationUploadRequest<Id>,
): Promise<api.ApiOperationResponse<Id>> {
  if (useProductionOperationClient && "apiOperationUpload" in api) {
    return api.apiOperationUpload(operationId, request);
  }
  const parts = request as OperationRequest & { body: FormData };
  return api.apiUpload(compatibilityPath(operationId, parts), parts.body, {
    method: API_OPERATIONS[operationId].method,
    headers: parts.headers,
    signal: parts.signal,
  });
}
