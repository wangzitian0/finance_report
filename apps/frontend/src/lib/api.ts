import { getAccessToken } from "./auth";
import type {
  BaseCurrency,
  ConfidenceNorthStarResponse,
  CorrectionLoopReplayResponse,
  CurrentUser,
  LlmCatalogResponse,
  LlmConfigStatusResponse,
  LlmModality,
  LlmProviderCreate,
  LlmProviderListResponse,
  LlmProviderResponse,
  LlmScenesResponse,
  LlmScenesUpdate,
  UserAiSettings,
  UserAiSettingsUpdate,
  WorkflowEventListResponse,
  WorkflowEventResponse,
  WorkflowEventStatus,
  WorkflowStatusResponse,
} from "./types";

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

  if (!redirecting) {
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

  constructor(
    message: string,
    status: number,
    errorId: string | null = null,
    requestId: string | null = null
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorId = errorId;
    this.requestId = requestId;
  }
}

/** Narrowing helper: true when `err` is an {@link ApiError} with the given code. */
export function isApiErrorCode(err: unknown, code: string): boolean {
  return err instanceof ApiError && err.errorId === code;
}

/** Parse a backend error body into `{ message, errorId, requestId }`. */
function parseApiError(
  errorText: string,
  status: number
): { message: string; errorId: string | null; requestId: string | null } {
  let message = `Request failed with ${status}`;
  let errorId: string | null = null;
  let requestId: string | null = null;
  if (errorText) {
    try {
      const parsed = JSON.parse(errorText);
      if (parsed && typeof parsed === "object") {
        const body = parsed as {
          detail?: unknown;
          error_id?: string;
          request_id?: string;
        };
        // FastAPI validation errors (422) return `detail` as an array of objects,
        // not a string. Only use it as the message when it's actually a string;
        // otherwise keep the raw text so users never see `[object Object]`.
        message = typeof body.detail === "string" ? body.detail : errorText;
        errorId = body.error_id ?? null;
        requestId = body.request_id ?? null;
      } else {
        message = errorText;
      }
    } catch {
      message = errorText;
    }
  }
  return { message, errorId, requestId };
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
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
    const { message, errorId, requestId } = parseApiError(errorText, res.status);
    throw new ApiError(message, res.status, errorId, requestId);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

export interface DownloadResponse {
  blob: Blob;
  filename: string | null;
}

function getFilenameFromContentDisposition(value: string | null): string | null {
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

export async function apiDownload(
  path: string,
  options: RequestInit = {}
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
    filename: getFilenameFromContentDisposition(res.headers.get("Content-Disposition")),
  };
}

export interface StreamResponse {
  response: Response;
  sessionId: string | null;
}

export async function apiStream(
  path: string,
  options: RequestInit = {}
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
    const { message, errorId, requestId } = parseApiError(errorText, res.status);
    throw new ApiError(message, res.status, errorId, requestId);
  }

  return {
    response: res,
    sessionId: res.headers.get("X-Session-Id"),
  };
}

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
    if (res.status === 401) {
      handle401Redirect();
    }
    throw new Error(`Delete failed with ${res.status}`);
  }
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
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
    const { message, errorId, requestId } = parseApiError(errorText, res.status);
    throw new ApiError(message, res.status, errorId, requestId);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

export interface FetchWorkflowEventsOptions {
  status?: WorkflowEventStatus;
  limit?: number;
}

export async function fetchWorkflowStatus(): Promise<WorkflowStatusResponse> {
  return apiFetch<WorkflowStatusResponse>("/api/workflow/status");
}

export async function fetchWorkflowEvents(
  options: FetchWorkflowEventsOptions = {}
): Promise<WorkflowEventListResponse> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  return apiFetch<WorkflowEventListResponse>(`/api/workflow/events${query ? `?${query}` : ""}`);
}

export async function updateWorkflowEventStatus(
  eventId: string,
  status: WorkflowEventStatus
): Promise<WorkflowEventResponse> {
  return apiFetch<WorkflowEventResponse>(`/api/workflow/events/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// ── North-Star confidence metric (EPIC-018 AC18.12 / #1003, #1055 PR4) ─────

/** The live low-confidence proportion plus its recorded trend (newest first). */
export async function fetchConfidenceNorthStar(): Promise<ConfidenceNorthStarResponse> {
  return apiFetch<ConfidenceNorthStarResponse>("/api/metrics/confidence-north-star");
}

/** The held-out replay of the correction loop — does it lower the proportion? */
export async function fetchCorrectionLoopReplay(): Promise<CorrectionLoopReplayResponse> {
  return apiFetch<CorrectionLoopReplayResponse>("/api/metrics/correction-loop/replay");
}

// ── Current-user AI settings (EPIC-022 AC22.15 / #1010) ────────────────────

/** The effective AI feature flags for the signed-in user. */
export async function fetchUserSettings(): Promise<UserAiSettings> {
  return apiFetch<UserAiSettings>("/api/users/me/settings");
}

/** Persist current-user AI setting overrides and return the effective flags. */
export async function patchUserSettings(
  update: UserAiSettingsUpdate
): Promise<UserAiSettings> {
  return apiFetch<UserAiSettings>("/api/users/me/settings", {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

// ── App-level base currency (EPIC-012 AC12.39 / #1340) ─────────────────────

/** The effective base reporting currency (persisted override else env default). */
export async function fetchBaseCurrency(): Promise<BaseCurrency> {
  return apiFetch<BaseCurrency>("/api/app-config/base-currency");
}

/** Persist a new effective base reporting currency (ISO 4217). */
export async function updateBaseCurrency(
  baseCurrency: string
): Promise<BaseCurrency> {
  return apiFetch<BaseCurrency>("/api/app-config/base-currency", {
    method: "PUT",
    body: JSON.stringify({ base_currency: baseCurrency }),
  });
}

// ── Session bootstrap (EPIC-022 AC22.15 / #1010) ───────────────────────────

/** The authenticated identity backing the current session cookie/token. */
export async function fetchCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/auth/me");
}

// ── LLM configuration (EPIC-023 PR4) ───────────────────────────────────────

/** Whether the current user has a usable LLM configuration (drives first-run). */
export async function fetchLlmConfigStatus(): Promise<LlmConfigStatusResponse> {
  return apiFetch<LlmConfigStatusResponse>("/api/llm/config/status");
}

/** The current user's configured providers (API keys are never returned). */
export async function fetchLlmProviders(): Promise<LlmProviderListResponse> {
  return apiFetch<LlmProviderListResponse>("/api/llm/providers");
}

/** Create a provider instance for the current user (api_key is write-only). */
export async function createLlmProvider(
  body: LlmProviderCreate
): Promise<LlmProviderResponse> {
  return apiFetch<LlmProviderResponse>("/api/llm/providers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Delete a configured provider by id. */
export async function deleteLlmProvider(id: string): Promise<void> {
  return apiDelete(`/api/llm/providers/${id}`);
}

export interface FetchLlmCatalogOptions {
  modality?: LlmModality;
  freeOnly?: boolean;
}

/** The model catalogue, optionally filtered by modality and free-tier. */
export async function fetchLlmCatalog(
  options: FetchLlmCatalogOptions = {}
): Promise<LlmCatalogResponse> {
  const params = new URLSearchParams();
  if (options.modality) params.set("modality", options.modality);
  if (options.freeOnly !== undefined) {
    params.set("free_only", String(options.freeOnly));
  }
  const query = params.toString();
  return apiFetch<LlmCatalogResponse>(
    `/api/llm/catalog${query ? `?${query}` : ""}`
  );
}

/** The current user's scene→model bindings. */
export async function fetchLlmScenes(): Promise<LlmScenesResponse> {
  return apiFetch<LlmScenesResponse>("/api/llm/scenes");
}

/** Replace the current user's scene bindings (PUT semantics). */
export async function putLlmScenes(
  body: LlmScenesUpdate
): Promise<LlmScenesResponse> {
  return apiFetch<LlmScenesResponse>("/api/llm/scenes", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
