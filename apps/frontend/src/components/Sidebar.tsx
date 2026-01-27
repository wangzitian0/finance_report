"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";
import { ThemeToggle } from "@/components/ThemeToggle";
import { clearUser, getUserEmail, isAuthenticated } from "@/lib/auth";
import { useState, useEffect } from "react";
import {
    LayoutDashboard,
    Landmark,
    BookOpen,
    FileText,
    Wallet,
    BarChart3,
    Link2,
    MessageSquare,
    Zap,
    LogOut,
    LogIn,
    type LucideIcon,
} from "lucide-react";

// Hide dev routes in production
const IS_DEV = process.env.NODE_ENV === "development";

interface NavItem {
    icon: LucideIcon;
    label: string;
    href: string;
    protected: boolean;
}

const navItems: NavItem[] = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard", protected: true },
    { icon: Landmark, label: "Accounts", href: "/accounts", protected: true },
    { icon: BookOpen, label: "Journal", href: "/journal", protected: true },
    { icon: FileText, label: "Statements", href: "/statements", protected: true },
    { icon: Wallet, label: "Assets", href: "/assets", protected: true },
    { icon: BarChart3, label: "Reports", href: "/reports", protected: true },
    { icon: Link2, label: "Reconciliation", href: "/reconciliation", protected: true },
    { icon: MessageSquare, label: "AI Advisor", href: "/chat", protected: true },
];

export function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const { isCollapsed, toggleSidebar } = useWorkspace();
    const [userEmail, setUserEmail] = useState<string | null>(null);
    const [isAuth, setIsAuth] = useState(false);

    useEffect(() => {
        setUserEmail(getUserEmail());
        setIsAuth(isAuthenticated());
    }, [pathname]);

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
                            Finance
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    {!isCollapsed && <ThemeToggle />}
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
            <nav className="p-2 space-y-0.5">
                {navItems.filter(item => isAuth || !item.protected).map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                    const IconComponent = item.icon;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`
                flex items-center gap-2.5 px-2.5 py-2.5 rounded-md
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
                            <IconComponent className="w-5 h-5 flex-shrink-0" aria-hidden="true" />
                            {!isCollapsed && <span className="font-medium">{item.label}</span>}
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
            flex items-center gap-2.5 px-2.5 py-2.5 rounded-md
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
                w-full flex items-center gap-2.5 px-2.5 py-2.5 rounded-md
                text-red-500 hover:bg-red-500/10
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
                flex items-center gap-2.5 px-2.5 py-2.5 rounded-md
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
