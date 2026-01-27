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

interface RouteConfig {
    label: string;
    Icon: LucideIcon;
}

const ROUTE_CONFIG: Record<string, RouteConfig> = {
    "/dashboard": { label: "Dashboard", Icon: LayoutDashboard },
    "/accounts": { label: "Accounts", Icon: Landmark },
    "/journal": { label: "Journal", Icon: BookOpen },
    "/statements": { label: "Statements", Icon: FileText },
    "/assets": { label: "Assets", Icon: Landmark },
    "/reports": { label: "Reports", Icon: BarChart3 },
    "/reports/balance-sheet": { label: "Balance Sheet", Icon: BarChart3 },
    "/reports/income-statement": { label: "Income Statement", Icon: BarChart3 },
    "/reports/cash-flow": { label: "Cash Flow", Icon: BarChart3 },
    "/reconciliation": { label: "Reconciliation", Icon: Link2 },
    "/reconciliation/unmatched": { label: "Unmatched", Icon: Link2 },
    "/chat": { label: "AI Advisor", Icon: MessageSquare },
    "/ping-pong": { label: "Ping-Pong", Icon: Zap },
};

const DEFAULT_ICON = FileText;

function getRouteConfig(pathname: string): RouteConfig {
    if (ROUTE_CONFIG[pathname]) return ROUTE_CONFIG[pathname];
    const segments = pathname.split("/").filter(Boolean);
    while (segments.length > 0) {
        const parentPath = "/" + segments.join("/");
        if (ROUTE_CONFIG[parentPath]) return ROUTE_CONFIG[parentPath];
        segments.pop();
    }
    const derivedSegments = pathname.split("/").filter(Boolean);
    const lastSegment = derivedSegments[derivedSegments.length - 1];
    const rawLabel = lastSegment ?? "Page";
    const label = rawLabel.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    return { label, Icon: DEFAULT_ICON };
}

export function WorkspaceTabs() {
    const pathname = usePathname();
    const { tabs, activeTabId, addTab, removeTab, setActiveTab } = useWorkspace();

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
    const config = ROUTE_CONFIG[tab.href];
    const IconComponent = config?.Icon ?? DEFAULT_ICON;

    return (
        <div
            className={`
        group flex items-center gap-1.5 px-3 py-2.5 rounded-md min-h-[44px]
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
                className={`p-2 -m-1 rounded hover:bg-[var(--background-muted)] transition-opacity ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                aria-label={`Close ${tab.label} tab`}
            >
                <X className="w-3 h-3" aria-hidden="true" />
            </button>
        </div>
    );
}
