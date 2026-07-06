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
                        isActive={tab.id === activeTabId || tab.href === pathname}
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
