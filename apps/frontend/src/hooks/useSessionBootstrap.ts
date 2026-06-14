"use client";

import { useEffect } from "react";

import { fetchCurrentUser } from "@/lib/api";
import { clearUser, getUserId, setUser } from "@/lib/auth";

/**
 * Session bootstrap (EPIC-022 AC22.15 / #1010).
 *
 * Consumes `GET /api/auth/me` once on mount to confirm the cookie-backed
 * session is still valid and to keep the locally-cached user identity in sync
 * with the authoritative backend. Without this, `/auth/me` was registered and
 * backend-tested but never consumed by the frontend.
 *
 * - Only runs when a local session id is present (skips the login route, which
 *   renders outside the authenticated shell).
 * - On success, refreshes the cached id/email from the backend response.
 * - The shared `apiFetch` client already redirects to `/login` on a 401; any
 *   other failure clears the stale local identity defensively.
 */
export function useSessionBootstrap(): void {
    useEffect(() => {
        if (getUserId() === null) return;

        let cancelled = false;
        void (async () => {
            try {
                const user = await fetchCurrentUser();
                if (!cancelled) {
                    setUser(user.id, user.email);
                }
            } catch {
                // 401 is handled by apiFetch (redirect to /login). For any other
                // failure, drop the stale local identity rather than trusting it.
                if (!cancelled) {
                    clearUser();
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, []);
}
