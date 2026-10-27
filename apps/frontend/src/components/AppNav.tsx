"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { LogIn, LogOut, X } from "lucide-react";
import { useLogout } from "@/hooks/useLogout";
import { useWorkspace, WorkspaceTab } from "@/hooks/useWorkspace";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getUserEmail, isAuthenticated } from "@/lib/auth";
import { ADD_ACTION, bottomTabItems, isActive, type NavItem, getRouteConfig } from "@/components/navigation";
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

    const { handleLogout, isLoggingOut, logoutError } = useLogout();

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
        ${isCollapsed ? "w-16" : "w-64"}
      `}
        >
            {/* Logo & Collapse Toggle */}
            <div className="flex items-center justify-between gap-2 h-14 px-3 border-b border-[var(--border)]">
                <Link href="/" className="flex min-w-0 items-center gap-2" aria-label="Finance Report home">
                    <div className="w-8 h-8 bg-[var(--accent)] rounded-md flex items-center justify-center flex-shrink-0">
                        <span className="text-white font-bold text-sm">$</span>
                    </div>
                    {!isCollapsed && (
                        <span className="font-semibold text-sm whitespace-nowrap">
                            Finance Report
                        </span>
                    )}
                </Link>
                <div className="flex shrink-0 items-center gap-1">
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
                        disabled={isLoggingOut}
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

                {logoutError && <p role="alert" className="text-sm text-[var(--error)]">{logoutError}</p>}

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

export function WorkspaceTabs() {
    const pathname = usePathname();
    const router = useRouter();
    const { tabs, activeTabId, addTab, removeTab, setActiveTab } = useWorkspace();

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault();
            const currentIndex = tabs.findIndex((t) => t.href === pathname);
            if (currentIndex === -1) return;

            let nextIndex;
            if (e.key === "ArrowRight") {
                nextIndex = (currentIndex + 1) % tabs.length;
            } else {
                nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
            }

            const nextTab = tabs[nextIndex];
            setActiveTab(nextTab.id);
            router.push(nextTab.href);
        }
    };

    useEffect(() => {
        if (pathname && pathname !== "/") {
            const config = getRouteConfig(pathname);
            addTab({ label: config.label, href: pathname, icon: config.Icon.displayName ?? "default" });
        }
    }, [pathname, addTab]);

    useEffect(() => {
        const currentTab = tabs.find((t) => t.href === pathname);
        if (currentTab && currentTab.id !== activeTabId) setActiveTab(currentTab.id);
    }, [pathname, tabs, activeTabId, setActiveTab]);

    if (tabs.length === 0) {
        return (
            <nav aria-label="Open workspace tabs" className="h-11 bg-surface-card border-b border-border flex items-center px-3">
                <span className="text-xs font-medium text-muted uppercase tracking-wider mr-3">Open Tabs</span>
                <span className="text-muted text-sm">No tabs open</span>
            </nav>
        );
    }

    return (
        <nav
            aria-label="Open workspace tabs"
            onKeyDown={handleKeyDown}
            className="h-11 min-w-0 bg-surface-card border-b border-border flex items-center overflow-x-auto"
        >
            <span className="text-xs font-medium text-muted uppercase tracking-wider px-3 flex-shrink-0 border-r border-border h-full flex items-center mr-1">Open Tabs</span>
            <ol className="flex items-center gap-0.5 px-2">
                {tabs.map((tab) => (
                    <TabItem
                        key={tab.id}
                        tab={tab}
                        isActive={tab.href === pathname}
                        onClose={() => removeTab(tab.id)}
                        onClick={() => setActiveTab(tab.id)}
                    />
                ))}
            </ol>
        </nav>
    );
}

interface TabItemProps {
    tab: WorkspaceTab;
    isActive: boolean;
    onClose: () => void;
    onClick: () => void;
}

function TabItem({ tab, isActive, onClose, onClick }: TabItemProps) {
    const config = getRouteConfig(tab.href);
    const IconComponent = config.Icon;

    return (
        <li
            className={`
                group flex min-h-[44px] items-center gap-1.5 rounded-md text-sm transition-colors
                ${isActive
                    ? "bg-accent-muted text-accent"
                    : "text-muted hover:bg-surface-muted hover:text-content"
                }
            `}
        >
            <Link
                href={tab.href}
                aria-current={isActive ? "page" : undefined}
                className="flex min-h-[44px] items-center gap-1.5 px-3 py-2.5"
                onClick={onClick}
            >
                <IconComponent className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
                <span className="font-medium max-w-[100px] truncate">{tab.label}</span>
            </Link>
            <button
                onClick={onClose}
                className={`mr-1 inline-flex h-11 w-11 items-center justify-center rounded hover:bg-surface-muted transition-opacity ${isActive ? "opacity-100" : "invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 focus-visible:visible focus-visible:opacity-100"}`}
                aria-label={`Close ${tab.label} tab`}
            >
                <X className="w-4 h-4" aria-hidden="true" />
            </button>
        </li>
    );
}
