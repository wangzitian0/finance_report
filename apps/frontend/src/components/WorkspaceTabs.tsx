"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useWorkspace, WorkspaceTab } from "@/hooks/useWorkspace";

const routeInfo: Record<string, { label: string; icon: string }> = {
    "/dashboard": { label: "Dashboard", icon: "📊" },
    "/accounts": { label: "Accounts", icon: "🏦" },
    "/journal": { label: "Journal", icon: "📝" },
    "/statements": { label: "Statements", icon: "📄" },
    "/reports": { label: "Reports", icon: "📈" },
    "/reports/balance-sheet": { label: "Balance Sheet", icon: "📈" },
    "/reports/income-statement": { label: "Income Statement", icon: "📈" },
    "/reports/cash-flow": { label: "Cash Flow", icon: "📈" },
    "/reconciliation": { label: "Reconciliation", icon: "🔗" },
    "/reconciliation/unmatched": { label: "Unmatched", icon: "🔗" },
    "/chat": { label: "AI Advisor", icon: "💬" },
    "/ping-pong": { label: "Ping-Pong", icon: "🏓" },
};

function getRouteInfo(pathname: string): { label: string; icon: string } {
    if (routeInfo[pathname]) return routeInfo[pathname];
    const segments = pathname.split("/").filter(Boolean);
    while (segments.length > 0) {
        const parentPath = "/" + segments.join("/");
        if (routeInfo[parentPath]) return routeInfo[parentPath];
        segments.pop();
    }
    const derivedSegments = pathname.split("/").filter(Boolean);
    const lastSegment = derivedSegments[derivedSegments.length - 1];
    const rawLabel = lastSegment ?? "Page";
    const label = rawLabel.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    return { label, icon: "📄" };
}

export function WorkspaceTabs() {
    const pathname = usePathname();
    const { tabs, activeTabId, addTab, removeTab, setActiveTab } = useWorkspace();

    useEffect(() => {
        if (pathname && pathname !== "/") {
            const info = getRouteInfo(pathname);
            addTab({ label: info.label, href: pathname, icon: info.icon });
        }
    }, [pathname, addTab]);

    useEffect(() => {
        const currentTab = tabs.find((t) => t.href === pathname);
        if (currentTab && currentTab.id !== activeTabId) setActiveTab(currentTab.id);
    }, [pathname, tabs, activeTabId, setActiveTab]);

    if (tabs.length === 0) {
        return (
            <div className="h-10 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center px-3">
                <span className="text-muted text-sm">No tabs open</span>
            </div>
        );
    }

    return (
        <div className="h-10 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center overflow-x-auto">
            <div className="flex items-center gap-0.5 px-2">
                {tabs.map((tab) => (
                    <TabItem
                        key={tab.id}
                        tab={tab}
                        isActive={tab.id === activeTabId || tab.href === pathname}
                        onClose={() => removeTab(tab.id)}
                        onClick={() => setActiveTab(tab.id)}
                    />
                ))}
            </div>
        </div>
    );
}

interface TabItemProps {
    tab: WorkspaceTab;
    isActive: boolean;
    onClose: () => void;
    onClick: () => void;
}

function TabItem({ tab, isActive, onClose, onClick }: TabItemProps) {
    return (
        <div
            className={`
        group flex items-center gap-1.5 px-2.5 py-1 rounded-md
        transition-colors cursor-pointer select-none text-sm
        ${isActive
                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                }
      `}
            onClick={onClick}
        >
            <Link href={tab.href} className="flex items-center gap-1.5">
                {tab.icon && <span className="text-sm">{tab.icon}</span>}
                <span className="font-medium max-w-[100px] truncate">{tab.label}</span>
            </Link>
            <button
                onClick={(e) => { e.stopPropagation(); onClose(); }}
                className={`p-0.5 rounded hover:bg-[var(--background-muted)] transition-opacity ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                aria-label={`Close ${tab.label} tab`}
            >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
    );
}
