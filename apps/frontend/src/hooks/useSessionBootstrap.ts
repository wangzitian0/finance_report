"use client";

import { useEffect } from "react";

import { ApiError, apiOperation } from "@/lib/api-client";
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
 * - The shared `apiFetch` client already redirects to `/login` on a 401.
 * - Only a definite server answer that the identity is invalid (401, 403, or
 *   404) clears the local identity. An aborted request or a network error
 *   says nothing about the session, so it keeps the identity (#2478).
 */
const IDENTITY_REJECTED_STATUSES = new Set([401, 403, 404]);

function identityRejected(err: unknown): boolean {
    return err instanceof ApiError && IDENTITY_REJECTED_STATUSES.has(err.status);
}

export function useSessionBootstrap(): void {
    useEffect(() => {
        if (getUserId() === null) return;

        let cancelled = false;
        void (async () => {
            try {
                const user = await apiOperation("get_me_auth_me_get");
                if (!cancelled) {
                    setUser(user.id, user.email);
                }
            } catch (err) {
                // Drop the local identity only when the server rejects it. A
                // navigation abort or a network error keeps it (#2478).
                if (!cancelled && identityRejected(err)) {
                    clearUser();
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, []);
}
