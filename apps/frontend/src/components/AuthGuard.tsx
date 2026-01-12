"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/ping-pong"];

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

    // Show nothing while checking auth to prevent flash of content
    if (!authorized && !isPublicPath(pathname)) {
        return null;
    }

    return <>{children}</>;
}
