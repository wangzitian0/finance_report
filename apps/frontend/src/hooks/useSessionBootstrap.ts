"use client";

import { useEffect } from "react";

import { ApiError, apiOperation } from "@/lib/api-client";
import { clearUser, getUserId, setUser } from "@/lib/auth";

const REJECTED_STATUSES = new Set([401, 403, 404]);

export function useSessionBootstrap(): void {
  useEffect(() => {
    if (getUserId() === null) return;
    let cancelled = false;
    void apiOperation("get_me_auth_me_get")
      .then((user) => {
        if (!cancelled) setUser(user.id, user.email);
      })
      .catch((err: unknown) => {
        if (!cancelled && err instanceof ApiError && REJECTED_STATUSES.has(err.status)) {
          clearUser();
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);
}
