import { getAccessToken, getUserId } from "./auth";

/**
 * API base URL for backend requests.
 *
 * - Development: Empty string (Next.js rewrites proxy /api/* to backend)
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
    headers,
  });

  if (!res.ok) {
    const errorText = await res.text();
    let message = `Request failed with ${res.status}`;
    if (errorText) {
      try {
        const parsed = JSON.parse(errorText);
        if (parsed && typeof parsed === "object") {
          const detail = (parsed as { detail?: string }).detail;
          message = detail || errorText;
        } else {
          message = errorText;
        }
      } catch {
        message = errorText;
      }
    }
    throw new Error(message);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
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
    headers,
  });

  if (!res.ok) {
    const errorText = await res.text();
    let message = `Request failed with ${res.status}`;
    if (errorText) {
      try {
        const parsed = JSON.parse(errorText);
        if (parsed && typeof parsed === "object") {
          const detail = (parsed as { detail?: string }).detail;
          message = detail || errorText;
        } else {
          message = errorText;
        }
      } catch {
        message = errorText;
      }
    }
    throw new Error(message);
  }

  // 204 No Content has no response body
  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}
