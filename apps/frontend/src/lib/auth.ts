/**
 * Auth utilities for user session management.
 *
 * MVP: Stores user ID in localStorage for X-User-Id header injection.
 * SSR-safe: Returns null on server.
 */

const USER_KEY = "finance_user_id";
const USER_EMAIL_KEY = "finance_user_email";

export function getUserId(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(USER_KEY);
}

export function getUserEmail(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(USER_EMAIL_KEY);
}

export function setUser(userId: string, email: string): void {
    localStorage.setItem(USER_KEY, userId);
    localStorage.setItem(USER_EMAIL_KEY, email);
}

export function clearUser(): void {
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(USER_EMAIL_KEY);
}

export function isAuthenticated(): boolean {
    return getUserId() !== null;
}
