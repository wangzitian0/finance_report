"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";

interface NavItem {
    icon: string;
    label: string;
    href: string;
}

const navItems: NavItem[] = [
    { icon: "📊", label: "Dashboard", href: "/dashboard" },
    { icon: "🏦", label: "Accounts", href: "/accounts" },
    { icon: "📝", label: "Journal", href: "/journal" },
    { icon: "📄", label: "Statements", href: "/statements" },
    { icon: "📈", label: "Reports", href: "/reports" },
    { icon: "🔗", label: "Reconciliation", href: "/reconciliation" },
    { icon: "💬", label: "AI Advisor", href: "/chat" },
];

export function Sidebar() {
    const pathname = usePathname();
    const { isCollapsed, toggleSidebar } = useWorkspace();

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

            {/* Navigation */}
            <nav className="p-2 space-y-0.5">
                {navItems.map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`
                flex items-center gap-2.5 px-2.5 py-2 rounded-md
                transition-colors text-sm
                ${isActive
                                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                }
                ${isCollapsed ? "justify-center" : ""}
              `}
                            title={isCollapsed ? item.label : undefined}
                        >
                            <span className="text-base flex-shrink-0" role="img" aria-label={item.label}>
                                {item.icon}
                            </span>
                            {!isCollapsed && <span className="font-medium">{item.label}</span>}
                        </Link>
                    );
                })}
            </nav>

            {/* Bottom Section */}
            <div className="absolute bottom-0 left-0 right-0 p-2 border-t border-[var(--border)]">
                <Link
                    href="/ping-pong"
                    className={`
            flex items-center gap-2.5 px-2.5 py-2 rounded-md
            text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]
            transition-colors text-sm
            ${isCollapsed ? "justify-center" : ""}
          `}
                    title={isCollapsed ? "Ping-Pong Demo" : undefined}
                >
                    <span className="text-base flex-shrink-0">🏓</span>
                    {!isCollapsed && <span className="font-medium">Ping-Pong</span>}
                </Link>
            </div>
        </aside>
    );
}
