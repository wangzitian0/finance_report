"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";
import { ThemeToggle } from "@/components/ThemeToggle";
import { clearUser, getUserEmail, isAuthenticated } from "@/lib/auth";
import { fetchWorkflowStatus } from "@/lib/api";
import { advancedNavItems, primaryWorkflowNavItems, type NavItem } from "@/components/navigation";
import { useState, useEffect } from "react";
import { ChevronDown, FolderOpen, LogIn, LogOut, Zap } from "lucide-react";

// Hide dev routes in production
const IS_DEV = process.env.NODE_ENV === "development";

export function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const { isCollapsed, toggleSidebar } = useWorkspace();
    const [userEmail, setUserEmail] = useState<string | null>(null);
    const [isAuth, setIsAuth] = useState(false);
    const [advancedAttentionCount, setAdvancedAttentionCount] = useState(0);
    const [isAdvancedOpen, setIsAdvancedOpen] = useState(() =>
        advancedNavItems.some((item) => pathname === item.href || pathname.startsWith(item.href + "/")),
    );

    useEffect(() => {
        setUserEmail(getUserEmail());
        setIsAuth(isAuthenticated());
    }, [pathname]);

    useEffect(() => {
        if (!isAuth) {
            setAdvancedAttentionCount(0);
            return;
        }

        const fetchWorkflowAttention = async () => {
            try {
                const status = await fetchWorkflowStatus();
                const attentionCount = status.event_counts.blocked + status.event_counts.action_required;
                setAdvancedAttentionCount(attentionCount);
            } catch {
                setAdvancedAttentionCount(0);
            }
        };

        void fetchWorkflowAttention();
        const refreshInterval = window.setInterval(fetchWorkflowAttention, 30000);
        window.addEventListener("focus", fetchWorkflowAttention);

        return () => {
            window.clearInterval(refreshInterval);
            window.removeEventListener("focus", fetchWorkflowAttention);
        };
    }, [isAuth]);

    useEffect(() => {
        if (advancedNavItems.some((item) => pathname === item.href || pathname.startsWith(item.href + "/"))) {
            setIsAdvancedOpen(true);
        }
    }, [pathname]);

    const handleLogout = () => {
        clearUser();
        router.push("/login");
    };

    const renderNavLink = (item: NavItem, badgeCount = 0, inset = false) => {
        const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
        const IconComponent = item.icon;
        const label = badgeCount > 0 ? `${item.label} ${badgeCount}` : item.label;

        return (
            <Link
                key={item.href}
                href={item.href}
                className={`
                    relative flex items-center gap-2.5 rounded-md min-h-[44px]
                    transition-colors text-sm
                    ${inset ? "px-2.5 py-2.5" : "px-2.5 py-3"}
                    ${isActive
                        ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                        : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                    }
                    ${isCollapsed ? "justify-center" : ""}
                `}
                title={isCollapsed ? label : undefined}
                aria-label={isCollapsed ? label : undefined}
            >
                <span className="relative flex h-5 w-5 flex-shrink-0 items-center justify-center">
                    <IconComponent className="w-5 h-5" aria-hidden="true" />
                    {isCollapsed && badgeCount > 0 && (
                        <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-[var(--warning)] ring-2 ring-[var(--background-card)]" />
                    )}
                </span>
                {!isCollapsed && (
                    <>
                        <span className="font-medium">{item.label}</span>
                        {badgeCount > 0 && (
                            <span className="ml-auto inline-flex min-w-[1.5rem] items-center justify-center rounded-full bg-[var(--warning)] px-1.5 py-0.5 text-xs font-semibold text-white">
                                {badgeCount > 99 ? "99+" : badgeCount}
                            </span>
                        )}
                    </>
                )}
            </Link>
        );
    };

    const visiblePrimaryItems = primaryWorkflowNavItems.filter(item => isAuth || !item.protected);
    const visibleAdvancedItems = advancedNavItems.filter(item => isAuth || !item.protected);
    const isAdvancedActive = visibleAdvancedItems.some((item) => pathname === item.href || pathname.startsWith(item.href + "/"));

    return (
        <aside
            className={`
        fixed left-0 top-0 z-40 h-screen
        bg-[var(--background-card)] border-r border-[var(--border)]
        transition-all duration-300 ease-in-out
        hidden md:block print:hidden
        ${isCollapsed ? "w-16" : "w-56"}
      `}
        >
            {/* Logo & Collapse Toggle */}
            <div className="flex items-center justify-between h-14 px-3 border-b border-[var(--border)]">
                <Link href="/" className="flex items-center gap-2.5 overflow-hidden" aria-label="Finance Report home">
                    <div className="w-8 h-8 bg-[var(--accent)] rounded-md flex items-center justify-center flex-shrink-0">
                        <span className="text-white font-bold text-sm">$</span>
                    </div>
                    {!isCollapsed && (
                        <span className="font-semibold text-sm whitespace-nowrap">
                            Finance Report
                        </span>
                    )}
                </Link>
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
                {visiblePrimaryItems.map((item) => renderNavLink(item))}

                {visibleAdvancedItems.length > 0 && (
                    <div className="pt-1">
                        <button
                            type="button"
                            onClick={() => setIsAdvancedOpen((open) => !open)}
                            className={`
                                relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-3 min-h-[44px]
                                text-sm transition-colors
                                ${isAdvancedActive
                                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                }
                                ${isCollapsed ? "justify-center" : ""}
                            `}
                            title={isCollapsed ? `Advanced${advancedAttentionCount > 0 ? ` ${advancedAttentionCount}` : ""}` : undefined}
                            aria-label={`Advanced${advancedAttentionCount > 0 ? ` ${advancedAttentionCount}` : ""}`}
                            aria-expanded={isAdvancedOpen}
                        >
                            <span className="relative flex h-5 w-5 flex-shrink-0 items-center justify-center">
                                <FolderOpen className="w-5 h-5" aria-hidden="true" />
                                {isCollapsed && advancedAttentionCount > 0 && (
                                    <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-[var(--warning)] ring-2 ring-[var(--background-card)]" />
                                )}
                            </span>
                            {!isCollapsed && (
                                <>
                                    <span className="font-medium">Advanced</span>
                                    {advancedAttentionCount > 0 && (
                                        <span className="ml-auto inline-flex min-w-[1.5rem] items-center justify-center rounded-full bg-[var(--warning)] px-1.5 py-0.5 text-xs font-semibold text-white">
                                            {advancedAttentionCount > 99 ? "99+" : advancedAttentionCount}
                                        </span>
                                    )}
                                    <ChevronDown
                                        className={`h-4 w-4 transition-transform ${isAdvancedOpen ? "rotate-180" : ""}`}
                                        aria-hidden="true"
                                    />
                                </>
                            )}
                        </button>

                        {isAdvancedOpen && (
                            <div className={`mt-1 space-y-0.5 ${isCollapsed ? "" : "pl-3"}`}>
                                {visibleAdvancedItems.map((item) => renderNavLink(item, 0, true))}
                            </div>
                        )}
                    </div>
                )}
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
