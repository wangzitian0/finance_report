"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useWorkspace, WorkspaceTab } from "@/hooks/useWorkspace";
import { X } from "lucide-react";
import { getRouteConfig } from "@/components/navigation";

export function WorkspaceTabs() {
    const pathname = usePathname();
    const router = useRouter();
    const { tabs, activeTabId, addTab, removeTab, setActiveTab } = useWorkspace();

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault();
            const currentIndex = tabs.findIndex((t) => t.id === activeTabId);
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
            <div className="h-11 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center px-3">
                <span className="text-xs font-medium text-muted uppercase tracking-wider mr-3">Open Tabs</span>
                <span className="text-muted text-sm">No tabs open</span>
            </div>
        );
    }

    return (
        <div className="h-11 min-w-0 bg-[var(--background-card)] border-b border-[var(--border)] flex items-center overflow-x-auto">
            <span className="text-xs font-medium text-muted uppercase tracking-wider px-3 flex-shrink-0 border-r border-[var(--border)] h-full flex items-center mr-1">Open Tabs</span>
            <div role="tablist" onKeyDown={handleKeyDown} className="flex items-center gap-0.5 px-2">
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
    const config = getRouteConfig(tab.href);
    const IconComponent = config.Icon;

    return (
        <div
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
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
