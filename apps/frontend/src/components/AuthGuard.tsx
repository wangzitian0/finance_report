"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/ping-pong"];
const AUTH_TOKEN_KEY = "finance_access_token";

function isPublicPath(pathname: string) {
    return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(path + "/"));
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
    const router = useRouter();
    const pathname = usePathname();
    const [authorized, setAuthorized] = useState(false);

    useEffect(() => {
        // Check if path is public
        if (isPublicPath(pathname)) {
            setAuthorized(true);
            return;
        }

        // Check auth
        if (!isAuthenticated()) {
            setAuthorized(false);
            router.push("/login");
        } else {
            setAuthorized(true);
        }
    }, [pathname, router]);

    useEffect(() => {
        const handleStorageChange = (e: StorageEvent) => {
            if (e.key !== AUTH_TOKEN_KEY) return;
            
            if (e.newValue === null && !isPublicPath(pathname)) {
                setAuthorized(false);
                router.push("/login");
            } else if (e.newValue !== null && pathname === "/login") {
                router.push("/dashboard");
            }
        };

        window.addEventListener("storage", handleStorageChange);
        return () => window.removeEventListener("storage", handleStorageChange);
    }, [pathname, router]);

    // Show nothing while checking auth to prevent flash of content
    if (!authorized && !isPublicPath(pathname)) {
        return null;
    }

    return <>{children}</>;
}
