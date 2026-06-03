"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";
import { ThemeToggle } from "@/components/ThemeToggle";
import { clearUser, getUserEmail, isAuthenticated } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { isAmountZero } from "@/lib/currency";
import type { ProcessingSummaryResponse } from "@/lib/types";
import { primaryNavItems } from "@/components/navigation";
import { useState, useEffect } from "react";
import { LogIn, LogOut, Zap } from "lucide-react";

// Hide dev routes in production
const IS_DEV = process.env.NODE_ENV === "development";

export function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const { isCollapsed, toggleSidebar } = useWorkspace();
    const [userEmail, setUserEmail] = useState<string | null>(null);
    const [isAuth, setIsAuth] = useState(false);
    const [pendingReviewCount, setPendingReviewCount] = useState(0);
    const [hasProcessingBalanceWarning, setHasProcessingBalanceWarning] = useState(false);

    useEffect(() => {
        setUserEmail(getUserEmail());
        setIsAuth(isAuthenticated());
    }, [pathname]);

    useEffect(() => {
        if (!isAuth) {
            setPendingReviewCount(0);
            return;
        }

        const fetchPendingReviewCount = async () => {
            try {
                const [stage1, stage2] = await Promise.all([
                    apiFetch<{ items: Array<{ id: string }>; total: number }>("/api/statements/pending-review"),
                    apiFetch<{ pending_matches: Array<{ id: string; status: string }> }>("/api/statements/stage2/queue"),
                ]);

                const stage2Pending = stage2.pending_matches.filter((match) => match.status === "pending_review").length;
                setPendingReviewCount((stage1.total || 0) + stage2Pending);
            } catch {
                setPendingReviewCount(0);
            }
        };

        fetchPendingReviewCount();
        const refreshInterval = window.setInterval(fetchPendingReviewCount, 30000);
        window.addEventListener("focus", fetchPendingReviewCount);

        return () => {
            window.clearInterval(refreshInterval);
            window.removeEventListener("focus", fetchPendingReviewCount);
        };
    }, [isAuth]);

    useEffect(() => {
        if (!isAuth) {
            setHasProcessingBalanceWarning(false);
            return;
        }

        const fetchProcessingSummary = async () => {
            try {
                const summary = await apiFetch<ProcessingSummaryResponse>("/api/accounts/processing/summary");
                const balance = summary.current_balance ?? summary.pending_total ?? "0.00";
                setHasProcessingBalanceWarning(!isAmountZero(balance, 0));
            } catch {
                setHasProcessingBalanceWarning(false);
            }
        };

        fetchProcessingSummary();
        const refreshInterval = window.setInterval(fetchProcessingSummary, 30000);
        window.addEventListener("focus", fetchProcessingSummary);

        return () => {
            window.clearInterval(refreshInterval);
            window.removeEventListener("focus", fetchProcessingSummary);
        };
    }, [isAuth]);

    const handleLogout = () => {
        clearUser();
        router.push("/login");
    };

    return (
        <aside
            className={`
        fixed left-0 top-0 z-40 h-screen
        bg-[var(--background-card)] border-r border-[var(--border)]
        transition-all duration-300 ease-in-out
        hidden md:block
        ${isCollapsed ? "w-16" : "w-56"}
      `}
        >
            {/* Logo & Collapse Toggle */}
            <div className="flex items-center justify-between h-14 px-3 border-b border-[var(--border)]">
                <div className="flex items-center gap-2.5 overflow-hidden">
                    <div className="w-8 h-8 bg-[var(--accent)] rounded-md flex items-center justify-center flex-shrink-0">
                        <span className="text-white font-bold text-sm">$</span>
                    </div>
                    {!isCollapsed && (
                        <span className="font-semibold text-sm whitespace-nowrap">
                            Finance Report
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <ThemeToggle />
                    <button
                        onClick={toggleSidebar}
                        className="p-1.5 rounded-md hover:bg-[var(--background-muted)] text-muted transition-colors"
                        aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                    >
                        <svg
                            className={`w-4 h-4 transition-transform ${isCollapsed ? "rotate-180" : ""}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                        </svg>
                    </button>
                </div>
            </div>

            {/* Navigation */}
            <nav className="p-2 space-y-0.5" aria-label="Sidebar navigation">
                {primaryNavItems.filter(item => isAuth || !item.protected).map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                    const IconComponent = item.icon;
                    const badgeCount = item.href === "/review" ? pendingReviewCount : 0;
                    const showProcessingWarning = item.href === "/processing" && hasProcessingBalanceWarning;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`
                relative flex items-center gap-2.5 px-2.5 py-3 rounded-md min-h-[44px]
                transition-colors text-sm
                ${isActive
                                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                }
                ${isCollapsed ? "justify-center" : ""}
              `}
                            title={isCollapsed ? item.label : undefined}
                            aria-label={isCollapsed ? item.label : undefined}
                        >
                            <span className="relative flex h-5 w-5 flex-shrink-0 items-center justify-center">
                                <IconComponent className="w-5 h-5" aria-hidden="true" />
                                {showProcessingWarning && (
                                    <span
                                        className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-[var(--warning)] ring-2 ring-[var(--background-card)]"
                                        aria-label="Processing Account has unresolved balance"
                                    />
                                )}
                            </span>
                            {!isCollapsed && (
                                <>
                                    <span className="font-medium">{item.label}</span>
                                    {badgeCount > 0 && (
                                        <span className="ml-auto inline-flex min-w-[1.5rem] items-center justify-center rounded-full bg-[var(--warning)] px-1.5 py-0.5 text-xs font-semibold text-white">
                                            {badgeCount}
                                        </span>
                                    )}
                                    {showProcessingWarning && (
                                        <span className="ml-auto h-2.5 w-2.5 rounded-full bg-[var(--warning)]" aria-hidden="true" />
                                    )}
                                </>
                            )}
                        </Link>
                    );
                })}
            </nav>

            {/* Bottom Section */}
            <div className="absolute bottom-0 left-0 right-0 p-2 border-t border-[var(--border)] space-y-1">
                {/* User Email */}
                {!isCollapsed && userEmail && (
                    <div className="px-2.5 py-1.5 text-xs text-[var(--foreground-muted)] truncate">
                        {userEmail}
                    </div>
                )}

                {/* Dev-only: Ping-Pong connectivity test */}
                {IS_DEV && (
                    <Link
                        href="/ping-pong"
                        className={`
            flex items-center gap-2.5 px-2.5 py-3 rounded-md min-h-[44px]
            text-[var(--foreground-muted)] hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]
            transition-colors text-sm
            ${isCollapsed ? "justify-center" : ""}
          `}
                        title={isCollapsed ? "Ping-Pong Demo" : undefined}
                        aria-label={isCollapsed ? "Ping-Pong Demo" : undefined}
                    >
                        <Zap className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                        {!isCollapsed && <span className="font-medium">Ping-Pong</span>}
                    </Link>
                )}

                {/* Logout Button */}
                {isAuth && (
                    <button
                        onClick={handleLogout}
                        className={`
                w-full flex items-center gap-2.5 px-2.5 py-3 rounded-md min-h-[44px]
                text-[var(--error)] hover:bg-[var(--error-muted)]
                transition-colors text-sm
                ${isCollapsed ? "justify-center" : ""}
              `}
                        title={isCollapsed ? "Logout" : undefined}
                        aria-label={isCollapsed ? "Logout" : undefined}
                    >
                        <LogOut className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                        {!isCollapsed && <span className="font-medium">Logout</span>}
                    </button>
                )}

                {/* Login Link (if not auth) */}
                {!isAuth && (
                    <Link
                        href="/login"
                        className={`
                flex items-center gap-2.5 px-2.5 py-3 rounded-md min-h-[44px]
                text-[var(--accent)] hover:bg-[var(--accent-muted)]
                transition-colors text-sm
                ${isCollapsed ? "justify-center" : ""}
              `}
                        title={isCollapsed ? "Login" : undefined}
                        aria-label={isCollapsed ? "Login" : undefined}
                    >
                        <LogIn className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                        {!isCollapsed && <span className="font-medium">Login</span>}
                    </Link>
                )}
            </div>
        </aside>
    );
}
