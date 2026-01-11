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
    const { isCollapsed, toggleSidebar, addTab } = useWorkspace();

    const handleNavClick = (item: NavItem) => {
        addTab({ label: item.label, href: item.href, icon: item.icon });
    };

    return (
        <aside
            className={`
        fixed left-0 top-0 z-40 h-screen
        bg-[#0f1419] border-r border-slate-800
        transition-all duration-300 ease-in-out
        ${isCollapsed ? "w-16" : "w-64"}
      `}
        >
            {/* Logo & Collapse Toggle */}
            <div className="flex items-center justify-between h-16 px-4 border-b border-slate-800">
                <div className="flex items-center gap-3 overflow-hidden">
                    <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-lg flex items-center justify-center flex-shrink-0">
                        <span className="text-white font-bold text-sm">₿</span>
                    </div>
                    {!isCollapsed && (
                        <span className="text-white font-semibold text-lg whitespace-nowrap">
                            Finance
                        </span>
                    )}
                </div>
                <button
                    onClick={toggleSidebar}
                    className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
                    aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                    <svg
                        className={`w-4 h-4 transition-transform ${isCollapsed ? "rotate-180" : ""}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
                        />
                    </svg>
                </button>
            </div>

            {/* Navigation */}
            <nav className="p-3 space-y-1">
                {navItems.map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");

                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            onClick={() => handleNavClick(item)}
                            className={`
                flex items-center gap-3 px-3 py-2.5 rounded-xl
                transition-all duration-200
                ${isActive
                                    ? "bg-emerald-500/10 text-emerald-400 shadow-lg shadow-emerald-500/5"
                                    : "text-slate-400 hover:bg-slate-800 hover:text-white"
                                }
                ${isCollapsed ? "justify-center" : ""}
              `}
                            title={isCollapsed ? item.label : undefined}
                        >
                            <span className="text-lg flex-shrink-0" role="img" aria-label={item.label}>
                                {item.icon}
                            </span>
                            {!isCollapsed && (
                                <span className="font-medium text-sm">{item.label}</span>
                            )}
                        </Link>
                    );
                })}
            </nav>

            {/* Bottom Section */}
            <div className="absolute bottom-0 left-0 right-0 p-3 border-t border-slate-800">
                <Link
                    href="/ping-pong"
                    className={`
            flex items-center gap-3 px-3 py-2.5 rounded-xl
            text-slate-500 hover:bg-slate-800 hover:text-slate-300
            transition-all duration-200
            ${isCollapsed ? "justify-center" : ""}
          `}
                    title={isCollapsed ? "Ping-Pong Demo" : undefined}
                >
                    <span className="text-lg flex-shrink-0">🏓</span>
                    {!isCollapsed && (
                        <span className="font-medium text-sm">Ping-Pong</span>
                    )}
                </Link>
            </div>
        </aside>
    );
}
