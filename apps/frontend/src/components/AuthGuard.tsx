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

    if (!authorized && !isPublicPath(pathname)) {
        return (
            <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
                <div className="animate-pulse space-y-4 w-full max-w-md px-4">
                    <div className="h-8 bg-[var(--background-muted)] rounded w-3/4" />
                    <div className="h-4 bg-[var(--background-muted)] rounded w-full" />
                    <div className="h-4 bg-[var(--background-muted)] rounded w-5/6" />
                    <div className="h-32 bg-[var(--background-muted)] rounded w-full" />
                </div>
            </div>
        );
    }

    return <>{children}</>;
}
