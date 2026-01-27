"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useWorkspace, WorkspaceTab } from "@/hooks/useWorkspace";
import {
    LayoutDashboard,
    Landmark,
    BookOpen,
    FileText,
    BarChart3,
    Link2,
    MessageSquare,
    Zap,
    X,
    type LucideIcon,
} from "lucide-react";

type IconName = "dashboard" | "accounts" | "journal" | "statements" | "reports" | "reconciliation" | "chat" | "ping-pong" | "default";

const iconMap: Record<IconName, LucideIcon> = {
    dashboard: LayoutDashboard,
    accounts: Landmark,
    journal: BookOpen,
    statements: FileText,
    reports: BarChart3,
    reconciliation: Link2,
    chat: MessageSquare,
    "ping-pong": Zap,
    default: FileText,
};

const routeInfo: Record<string, { label: string; iconName: IconName }> = {
    "/dashboard": { label: "Dashboard", iconName: "dashboard" },
    "/accounts": { label: "Accounts", iconName: "accounts" },
    "/journal": { label: "Journal", iconName: "journal" },
    "/statements": { label: "Statements", iconName: "statements" },
    "/assets": { label: "Assets", iconName: "accounts" },
    "/reports": { label: "Reports", iconName: "reports" },
    "/reports/balance-sheet": { label: "Balance Sheet", iconName: "reports" },
    "/reports/income-statement": { label: "Income Statement", iconName: "reports" },
    "/reports/cash-flow": { label: "Cash Flow", iconName: "reports" },
    "/reconciliation": { label: "Reconciliation", iconName: "reconciliation" },
    "/reconciliation/unmatched": { label: "Unmatched", iconName: "reconciliation" },
    "/chat": { label: "AI Advisor", iconName: "chat" },
    "/ping-pong": { label: "Ping-Pong", iconName: "ping-pong" },
};

function getRouteInfo(pathname: string): { label: string; iconName: IconName } {
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
    return { label, iconName: "default" };
}

function getIconComponent(iconName: string | undefined): LucideIcon {
    if (!iconName) return iconMap.default;
    return iconMap[iconName as IconName] ?? iconMap.default;
}

export function WorkspaceTabs() {
    const pathname = usePathname();
    const { tabs, activeTabId, addTab, removeTab, setActiveTab } = useWorkspace();

    useEffect(() => {
        if (pathname && pathname !== "/") {
            const info = getRouteInfo(pathname);
            addTab({ label: info.label, href: pathname, icon: info.iconName });
        }
    }, [pathname, addTab]);

    useEffect(() => {
        const currentTab = tabs.find((t) => t.href === pathname);
        if (currentTab && currentTab.id !== activeTabId) setActiveTab(currentTab.id);
    }, [pathname, tabs, activeTabId, setActiveTab]);

    if (tabs.length === 0) {
        return (
            <div className="h-11 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center px-3">
                <span className="text-muted text-sm">No tabs open</span>
            </div>
        );
    }

    return (
        <div className="h-11 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center overflow-x-auto">
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
    const IconComponent = getIconComponent(tab.icon);

    return (
        <div
            className={`
        group flex items-center gap-1.5 px-2.5 py-2 rounded-md
        transition-colors cursor-pointer select-none text-sm
        ${isActive
                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                }
      `}
            onClick={onClick}
        >
            <Link href={tab.href} className="flex items-center gap-1.5">
                <IconComponent className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
                <span className="font-medium max-w-[100px] truncate">{tab.label}</span>
            </Link>
            <button
                onClick={(e) => { e.stopPropagation(); onClose(); }}
                className={`p-1 -m-0.5 rounded hover:bg-[var(--background-muted)] transition-opacity ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                aria-label={`Close ${tab.label} tab`}
            >
                <X className="w-3 h-3" aria-hidden="true" />
            </button>
        </div>
    );
}
