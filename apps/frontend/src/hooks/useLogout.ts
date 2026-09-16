"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiOperation } from "@/lib/api-client";
import { clearUser } from "@/lib/auth";

/** End browser cookie authority before reporting successful logout. */
export function useLogout() {
  const router = useRouter();
  const inFlight = useRef(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const handleLogout = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setIsLoggingOut(true);
    setLogoutError(null);
    try {
      await apiOperation("logout_auth_logout_post");
      clearUser();
      router.push("/login");
    } catch {
      setLogoutError("Could not log out. Please try again.");
    } finally {
      inFlight.current = false;
      setIsLoggingOut(false);
    }
  };

  return { handleLogout, isLoggingOut, logoutError };
}
