export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
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
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: formData,
    ...options,
    headers: {
      // Do NOT set Content-Type for FormData - browser sets it with boundary
      ...(options.headers || {}),
    },
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
