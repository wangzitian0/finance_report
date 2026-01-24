"use client";

import React, { createContext, useContext, useCallback, useState, useEffect } from "react";

export interface WorkspaceTab {
    id: string;
    label: string;
    href: string;
    icon?: string;
}

interface WorkspaceContextValue {
    tabs: WorkspaceTab[];
    activeTabId: string | null;
    addTab: (tab: Omit<WorkspaceTab, "id">) => void;
    removeTab: (id: string) => void;
    setActiveTab: (id: string) => void;
    isCollapsed: boolean;
    toggleSidebar: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const STORAGE_KEY = "finance-workspace-tabs";

function generateId(): string {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID();
    }
    return Math.random().toString(36).substring(2, 9);
}

interface WorkspaceProviderProps {
    children: React.ReactNode;
}

export function WorkspaceProvider({ children }: WorkspaceProviderProps) {
    const [tabs, setTabs] = useState<WorkspaceTab[]>([]);
    const [activeTabId, setActiveTabId] = useState<string | null>(null);
    const [isCollapsed, setIsCollapsed] = useState(false);
    const [isHydrated, setIsHydrated] = useState(false);

    useEffect(() => {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                if (parsed.tabs?.length) {
                    setTabs(parsed.tabs);
                    setActiveTabId(parsed.activeTabId || parsed.tabs[0]?.id);
                }
            }
        } catch (error) {
            if (process.env.NODE_ENV === "development") {
                // eslint-disable-next-line no-console
                console.error("Failed to load workspace tabs:", error);
            }
        }
        setIsHydrated(true);
    }, []);

    useEffect(() => {
        if (!isHydrated) return;
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({ tabs, activeTabId }));
        } catch (error) {
            if (process.env.NODE_ENV === "development") {
                // eslint-disable-next-line no-console
                console.error("Failed to save workspace tabs:", error);
            }
        }
    }, [tabs, activeTabId, isHydrated]);

    useEffect(() => {
        const handleStorageChange = (e: StorageEvent) => {
            if (e.key !== STORAGE_KEY || !e.newValue) return;
            try {
                const parsed = JSON.parse(e.newValue);
                if (parsed.tabs) {
                    setTabs(parsed.tabs);
                    setActiveTabId(parsed.activeTabId || parsed.tabs[0]?.id || null);
                }
            } catch {
                // Ignore parse errors from other tabs
            }
        };

        window.addEventListener("storage", handleStorageChange);
        return () => window.removeEventListener("storage", handleStorageChange);
    }, []);

    const addTab = useCallback((tab: Omit<WorkspaceTab, "id">) => {
        setTabs((prev) => {
            const existing = prev.find((t) => t.href === tab.href);
            if (existing) {
                setActiveTabId(existing.id);
                return prev;
            }
            const newTab: WorkspaceTab = { ...tab, id: generateId() };
            setActiveTabId(newTab.id);
            return [...prev, newTab];
        });
    }, []);

    const removeTab = useCallback((id: string) => {
        setTabs((prev) => {
            const index = prev.findIndex((t) => t.id === id);
            const newTabs = prev.filter((t) => t.id !== id);

            setActiveTabId((currentActive) => {
                if (currentActive === id && newTabs.length > 0) {
                    const newIndex = Math.min(index, newTabs.length - 1);
                    return newTabs[newIndex]?.id || null;
                }
                return currentActive;
            });

            return newTabs;
        });
    }, []);

    const setActiveTab = useCallback((id: string) => {
        setActiveTabId(id);
    }, []);

    const toggleSidebar = useCallback(() => {
        setIsCollapsed((prev) => !prev);
    }, []);

    const contextValue = React.useMemo<WorkspaceContextValue>(() => ({
        tabs,
        activeTabId,
        addTab,
        removeTab,
        setActiveTab,
        isCollapsed,
        toggleSidebar,
    }), [tabs, activeTabId, addTab, removeTab, setActiveTab, isCollapsed, toggleSidebar]);

    return React.createElement(
        WorkspaceContext.Provider,
        { value: contextValue },
        children
    );
}

export function useWorkspace(): WorkspaceContextValue {
    const context = useContext(WorkspaceContext);
    if (!context) {
        throw new Error("useWorkspace must be used within a WorkspaceProvider");
    }
    return context;
}
