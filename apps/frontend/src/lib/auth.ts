/**
 * Auth utilities for user session management.
 *
 * MVP: Stores user ID in localStorage for X-User-Id header injection.
 * SSR-safe: Returns null on server.
 */

const USER_KEY = "finance_user_id";
const USER_EMAIL_KEY = "finance_user_email";
const TOKEN_KEY = "finance_access_token";

export function getUserId(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(USER_KEY);
}

export function getUserEmail(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(USER_EMAIL_KEY);
}

export function getAccessToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(TOKEN_KEY);
}

export function setUser(userId: string, email: string, token?: string): void {
    localStorage.setItem(USER_KEY, userId);
    localStorage.setItem(USER_EMAIL_KEY, email);
    if (token) {
        localStorage.setItem(TOKEN_KEY, token);
    }
}

export function clearUser(): void {
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(USER_EMAIL_KEY);
    localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
    return getUserId() !== null;
}
