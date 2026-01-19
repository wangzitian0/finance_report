import { getAccessToken, getUserId } from "./auth";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "";

/**
 * Base URL of the frontend application.
 *
 * Use this when you need to construct absolute URLs that point back to
 * the frontend app itself (for example, in redirects or UI components).
 * In development it defaults to `http://localhost:3000`.
 */
export const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAccessToken();
  const userId = getUserId();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
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

  return (await res.json()) as T;
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const token = getAccessToken();
  const userId = getUserId();
  const headers: HeadersInit = {
    // Do NOT set Content-Type for FormData - browser sets it with boundary
    ...(options.headers || {}),
  };

  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
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

  return (await res.json()) as T;
}
