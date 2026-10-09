import { getAccessToken } from "./auth";
import { API_OPERATIONS, type ApiOperationId } from "./api-operations";
import type { components, operations } from "./api-types";

/**
 * API base URL for backend requests.
 *
 * - Local development: Empty string can be proxied by Next.js rewrites
 * - Production: Can be empty (same-origin) or set to backend domain
 *
 * When empty, API calls use relative paths (e.g., /api/accounts).
 */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "")
  .trim()
  .replace(/\/$/, "");

/**
 * Base URL of the frontend application.
 *
 * Use this when you need to construct absolute URLs that point back to
 * the frontend app itself (e.g., in redirects or OAuth callbacks).
 *
 * - Development: Defaults to http://localhost:3000
 * - Production: Set via NEXT_PUBLIC_APP_URL (e.g., https://report.zitian.party)
 * - PR environments: Auto-set to https://report-pr-{number}.zitian.party
 */
export const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";

// Redirect guard to prevent concurrent 401s from racing
let redirecting = false;

function handle401Redirect(): never {
  if (typeof window === "undefined") {
    // SSR context - log for debugging
    console.error("[api] 401 Unauthorized in SSR context - cannot redirect");
    throw new Error("Authentication required");
  }

  if (!redirecting && window.location.pathname !== "/login") {
    redirecting = true;
    try {
      window.location.href = "/login";
    } catch (err) {
      console.error("[api] Failed to redirect to login:", err);
      throw new Error("Authentication required - redirect failed");
    }
  }
  throw new Error("Authentication required");
}

export function resetRedirectGuard(): void {
  redirecting = false;
}

/**
 * Structured API error (#1005).
 *
 * The backend returns `{ error_id, detail, request_id }` for every failure.
 * `ApiError` carries the machine-readable `errorId` so callers can branch on a
 * stable code (e.g. `err.errorId === "conflict"`) instead of matching `message`
 * text. It extends `Error`, so existing `err instanceof Error` / `err.message`
 * call sites keep working unchanged.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly errorId: string | null;
  readonly requestId: string | null;
  readonly body: ApiErrorEnvelope | null;

  constructor(
    message: string,
    status: number,
    errorId: string | null = null,
    requestId: string | null = null,
    body: ApiErrorEnvelope | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorId = errorId;
    this.requestId = requestId;
    this.body = body;
  }
}

export type ApiErrorEnvelope =
  | components["schemas"]["ErrorResponse"]
  | components["schemas"]["HTTPValidationError"];

/** Narrowing helper: true when `err` is an {@link ApiError} with the given code. */
export function isApiErrorCode(err: unknown, code: string): boolean {
  return err instanceof ApiError && err.errorId === code;
}

/** Parse a backend error body into `{ message, errorId, requestId }`. */
function parseApiError(
  errorText: string,
  status: number,
): {
  message: string;
  errorId: string | null;
  requestId: string | null;
  body: ApiErrorEnvelope | null;
} {
  let message = `Request failed with ${status}`;
  let errorId: string | null = null;
  let requestId: string | null = null;
  let body: ApiErrorEnvelope | null = null;
  if (errorText) {
    try {
      const parsed = JSON.parse(errorText);
      if (parsed && typeof parsed === "object") {
        body = parsed as ApiErrorEnvelope;
        const parsedBody = parsed as {
          detail?: unknown;
          error_id?: string;
          request_id?: string;
        };
        // FastAPI validation errors (422) return `detail` as an array of objects,
        // not a string. Only use it as the message when it's actually a string;
        // otherwise keep the raw text so users never see `[object Object]`.
        message =
          typeof parsedBody.detail === "string" ? parsedBody.detail : errorText;
        errorId = parsedBody.error_id ?? null;
        requestId = parsedBody.request_id ?? null;
      } else {
        message = errorText;
      }
    } catch {
      message = errorText;
    }
  }
  return { message, errorId, requestId, body };
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  // Guard: Ensure path starts with / to avoid "http://hostpath" concatenation errors
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const res = await fetch(`${API_URL}${normalizedPath}`, {
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  });

  if (!res.ok) {
    if (res.status === 401) {
      handle401Redirect();
    }

    const errorText = await res.text();
    const { message, errorId, requestId, body } = parseApiError(
      errorText,
      res.status,
    );
    throw new ApiError(message, res.status, errorId, requestId, body);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

/** @deprecated Compatibility seam for existing tests; production callers must use apiOperation. */
export const apiFetch = requestJson;

type ParametersOf<Id extends ApiOperationId> = operations[Id]["parameters"];
type RequiredParameter<
  Id extends ApiOperationId,
  Name extends "path" | "query",
> =
  ParametersOf<Id> extends Record<Name, infer Value>
    ? [Value] extends [never]
      ? {}
      : { [Key in Name]: Value }
    : ParametersOf<Id> extends Partial<Record<Name, infer Value>>
      ? [Value] extends [never]
        ? {}
        : { [Key in Name]?: Value }
      : {};
type RequestBodyOf<Id extends ApiOperationId> = operations[Id] extends {
  requestBody: { content: { "application/json": infer Body } };
}
  ? { body: Body }
  : operations[Id] extends {
        requestBody?: { content: { "application/json": infer Body } };
      }
    ? { body?: Body }
    : {};
type JsonContent<Value> = Value extends {
  content: { "application/json": infer Body };
}
  ? Body
  : undefined;
type SuccessStatus = 200 | 201 | 202 | 204;
export type ApiOperationResponse<Id extends ApiOperationId> = JsonContent<
  operations[Id]["responses"][Extract<
    keyof operations[Id]["responses"],
    SuccessStatus
  >]
>;
export type ApiOperationRequest<Id extends ApiOperationId> = RequiredParameter<
  Id,
  "path"
> &
  RequiredParameter<Id, "query"> &
  RequestBodyOf<Id> & {
    headers?: HeadersInit;
    signal?: AbortSignal;
  };
type RequiredKeys<Value> = {
  [Key in keyof Value]-?: object extends Pick<Value, Key> ? never : Key;
}[keyof Value];
export type ApiOperationArgs<Id extends ApiOperationId> =
  RequiredKeys<ApiOperationRequest<Id>> extends never
    ? [request?: ApiOperationRequest<Id>]
    : [request: ApiOperationRequest<Id>];
export type MultipartOperationId = {
  [Id in ApiOperationId]: operations[Id] extends {
    requestBody: { content: { "multipart/form-data": unknown } };
  }
    ? Id
    : never;
}[ApiOperationId];
export type ApiOperationUploadRequest<Id extends MultipartOperationId> =
  RequiredParameter<Id, "path"> &
    RequiredParameter<Id, "query"> & {
      body: FormData;
      headers?: HeadersInit;
      signal?: AbortSignal;
    };

function materializeOperationPath(
  template: string,
  pathParameters: Record<string, unknown> | undefined,
): string {
  return template.replace(/\{([^}]+)\}/g, (_placeholder, name: string) => {
    const value = pathParameters?.[name];
    if (value === undefined || value === null) {
      throw new Error(`Missing OpenAPI path parameter: ${name}`);
    }
    return encodeURIComponent(String(value));
  });
}

function appendOperationQuery(path: string, query: object | undefined): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [name, rawValue] of Object.entries(query)) {
    if (rawValue === undefined || rawValue === null) continue;
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) params.append(name, String(value));
  }
  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export async function apiOperation<Id extends ApiOperationId>(
  operationId: Id,
  ...args: ApiOperationArgs<Id>
): Promise<ApiOperationResponse<Id>> {
  const request = (args[0] ?? {}) as ApiOperationRequest<Id>;
  const definition = API_OPERATIONS[operationId];
  const parts = request as {
    path?: Record<string, unknown>;
    query?: object;
    body?: unknown;
    headers?: HeadersInit;
    signal?: AbortSignal;
  };
  const path = appendOperationQuery(
    materializeOperationPath(definition.path, parts.path),
    parts.query,
  );
  return requestJson<ApiOperationResponse<Id>>(path, {
    method: definition.method,
    body: parts.body === undefined ? undefined : JSON.stringify(parts.body),
    headers: parts.headers,
    signal: parts.signal,
  });
}

export async function apiOperationStream<Id extends ApiOperationId>(
  operationId: Id,
  request: ApiOperationRequest<Id>,
): Promise<StreamResponse> {
  const definition = API_OPERATIONS[operationId];
  const parts = request as {
    path?: Record<string, unknown>;
    query?: object;
    body?: unknown;
    headers?: HeadersInit;
    signal?: AbortSignal;
  };
  const path = appendOperationQuery(
    materializeOperationPath(definition.path, parts.path),
    parts.query,
  );
  return requestStream(path, {
    method: definition.method,
    body: parts.body === undefined ? undefined : JSON.stringify(parts.body),
    headers: parts.headers,
    signal: parts.signal,
  });
}

export interface DownloadResponse {
  blob: Blob;
  filename: string | null;
}

function getFilenameFromContentDisposition(
  value: string | null,
): string | null {
  if (!value) return null;

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }

  const match = value.match(/filename=(?:"([^"]+)"|([^;]+))/i);
  return match?.[1]?.trim() ?? match?.[2]?.trim() ?? null;
}

async function requestDownload(
  path: string,
  options: RequestInit = {},
): Promise<DownloadResponse> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const res = await fetch(`${API_URL}${normalizedPath}`, {
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  });

  if (!res.ok) {
    if (res.status === 401) {
      handle401Redirect();
    }

    const errorText = await res.text();
    throw new Error(errorText || `Download failed with ${res.status}`);
  }

  return {
    blob: await res.blob(),
    filename: getFilenameFromContentDisposition(
      res.headers.get("Content-Disposition"),
    ),
  };
}

/** @deprecated Compatibility seam; production callers must use apiOperationDownload. */
export const apiDownload = requestDownload;

export interface StreamResponse {
  response: Response;
  sessionId: string | null;
}

async function requestStream(
  path: string,
  options: RequestInit = {},
): Promise<StreamResponse> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const res = await fetch(`${API_URL}${normalizedPath}`, {
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  });

  if (!res.ok) {
    if (res.status === 401) {
      handle401Redirect();
    }

    const errorText = await res.text();
    const { message, errorId, requestId } = parseApiError(
      errorText,
      res.status,
    );
    throw new ApiError(message, res.status, errorId, requestId);
  }

  return {
    response: res,
    sessionId: res.headers.get("X-Session-Id"),
  };
}

/** @deprecated Compatibility seam; production callers must use apiOperationStream. */
export const apiStream = requestStream;

/** @deprecated Compatibility seam; production callers must use apiOperation. */
export async function apiDelete(path: string): Promise<void> {
  const token = getAccessToken();
  const headers: HeadersInit = {};
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const res = await fetch(`${API_URL}${normalizedPath}`, {
    method: "DELETE",
    credentials: "include",
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) handle401Redirect();
    throw new Error(`Delete failed with ${res.status}`);
  }
}

async function requestUpload<T>(
  path: string,
  formData: FormData,
  options: RequestInit,
): Promise<T> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    // Do NOT set Content-Type for FormData - browser sets it with boundary
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  // Guard: Ensure path starts with /
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const res = await fetch(`${API_URL}${normalizedPath}`, {
    method: "POST",
    body: formData,
    ...options,
    credentials: options.credentials ?? "include",
    headers,
  });

  if (!res.ok) {
    if (res.status === 401) {
      handle401Redirect();
    }

    const errorText = await res.text();
    const { message, errorId, requestId } = parseApiError(
      errorText,
      res.status,
    );
    throw new ApiError(message, res.status, errorId, requestId);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

/** @deprecated Compatibility seam; production callers must use apiOperationUpload. */
export function apiUpload<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {},
): Promise<T> {
  return requestUpload(path, formData, { method: "POST", ...options });
}

export async function apiOperationDownload<Id extends ApiOperationId>(
  operationId: Id,
  request: ApiOperationRequest<Id>,
): Promise<DownloadResponse> {
  const definition = API_OPERATIONS[operationId];
  const parts = request as {
    path?: Record<string, unknown>;
    query?: object;
    headers?: HeadersInit;
    signal?: AbortSignal;
  };
  const path = appendOperationQuery(
    materializeOperationPath(definition.path, parts.path),
    parts.query,
  );
  return requestDownload(path, {
    method: definition.method,
    headers: parts.headers,
    signal: parts.signal,
  });
}

export async function apiOperationUpload<Id extends MultipartOperationId>(
  operationId: Id,
  request: ApiOperationUploadRequest<Id>,
): Promise<ApiOperationResponse<Id>> {
  const definition = API_OPERATIONS[operationId];
  const parts = request as {
    path?: Record<string, unknown>;
    query?: object;
    body: FormData;
    headers?: HeadersInit;
    signal?: AbortSignal;
  };
  const path = appendOperationQuery(
    materializeOperationPath(definition.path, parts.path),
    parts.query,
  );
  return requestUpload<ApiOperationResponse<Id>>(path, parts.body, {
    method: definition.method,
    headers: parts.headers,
    signal: parts.signal,
  });
}
