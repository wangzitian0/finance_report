"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { LogIn, LogOut } from "lucide-react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { ThemeToggle } from "@/components/ThemeToggle";
import { clearUser, getUserEmail, isAuthenticated } from "@/lib/auth";
import { ADD_ACTION, bottomTabItems, isActive, type NavItem } from "@/components/navigation";
import AddSheet from "@/components/shell/AddSheet";

// EPIC-022 AC22.21.2: the desktop sidebar mirrors the mobile bottom tab bar —
// Home, Chat, a center-equivalent Add action, Audit, and More — so there is one
// IA in two form factors.
export function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const { isCollapsed, toggleSidebar } = useWorkspace();
    const [userEmail, setUserEmail] = useState<string | null>(null);
    const [isAuth, setIsAuth] = useState(false);
    const [addOpen, setAddOpen] = useState(false);

    useEffect(() => {
        setUserEmail(getUserEmail());
        setIsAuth(isAuthenticated());
    }, [pathname]);

    const handleLogout = () => {
        clearUser();
        router.push("/login");
    };

    const [home, chat, audit, more] = bottomTabItems;
    const AddIcon = ADD_ACTION.icon;

    const renderNavLink = (item: NavItem) => {
        const active = isActive(pathname, item.href);
        const Icon = item.icon;
        return (
            <Link
                key={item.href}
                href={item.href}
                className={`
                    relative flex items-center gap-2.5 rounded-md min-h-[44px] px-2.5 py-3
                    transition-colors text-sm
                    ${active
                        ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                        : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                    }
                    ${isCollapsed ? "justify-center" : ""}
                `}
                title={isCollapsed ? item.label : undefined}
                aria-label={isCollapsed ? item.label : undefined}
                aria-current={active ? "page" : undefined}
            >
                <Icon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
                {!isCollapsed && <span className="font-medium">{item.label}</span>}
            </Link>
        );
    };

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

            {/* Navigation — mirrors the bottom tab bar: Home, Chat, Add, Audit, More */}
            <nav className="p-2 space-y-0.5" aria-label="Sidebar navigation">
                {renderNavLink(home)}
                {isAuth && renderNavLink(chat)}
                {isAuth && (
                    <button
                        type="button"
                        onClick={() => setAddOpen(true)}
                        className={`
                            relative flex w-full items-center gap-2.5 rounded-md min-h-[44px] px-2.5 py-3
                            text-sm font-medium text-[var(--accent)] hover:bg-[var(--accent-muted)] transition-colors
                            ${isCollapsed ? "justify-center" : ""}
                        `}
                        title={isCollapsed ? ADD_ACTION.label : undefined}
                        aria-label={ADD_ACTION.label}
                    >
                        <AddIcon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
                        {!isCollapsed && <span>{ADD_ACTION.label}</span>}
                    </button>
                )}
                {isAuth && renderNavLink(audit)}
                {isAuth && renderNavLink(more)}
            </nav>

            {/* Bottom Section */}
            <div className="absolute bottom-0 left-0 right-0 p-2 border-t border-[var(--border)] space-y-1">
                {!isCollapsed && userEmail && (
                    <div className="px-2.5 py-1.5 text-xs text-[var(--foreground-muted)] truncate">
                        {userEmail}
                    </div>
                )}

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

            <AddSheet isOpen={addOpen} onClose={() => setAddOpen(false)} onUploadComplete={() => router.refresh()} />
        </aside>
    );
}
