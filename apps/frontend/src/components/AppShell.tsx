"use client";

import { ReactNode } from "react";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { useSessionBootstrap } from "@/hooks/useSessionBootstrap";
import { Sidebar } from "@/components/Sidebar";
import { MobileNav } from "@/components/MobileNav";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { ToastProvider } from "@/components/ui/Toast";
import { WorkflowNotificationCenter } from "@/components/workflow/WorkflowNotifications";
import { FirstRunModal } from "@/components/llm/FirstRunModal";

interface AppShellProps {
    children: ReactNode;
}

function AppShellContent({ children }: AppShellProps) {
    const { isCollapsed } = useWorkspace();
    // Confirm/refresh the authenticated session against /auth/me on mount.
    useSessionBootstrap();

    return (
        <div className="min-h-screen">
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-toast focus:rounded-control focus:bg-surface-card focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-content focus:shadow-floating focus:outline-none focus:ring-2 focus:ring-accent"
            >
                Skip to main content
            </a>
            <Sidebar />

            {/* Main Content Area. On print, drop the sidebar offset so report
                output uses the full page (EPIC-022 #867 readable export). */}
            <div
                className={`transition-all duration-300 ease-in-out print:!ml-0 ${
                    isCollapsed ? "md:ml-16" : "md:ml-64"
                }`}
            >
                <div className="flex min-w-0 items-center border-b border-border bg-surface-card print:hidden">
                    <MobileNav />
                    <div className="hidden md:block min-w-0 flex-1">
                        <WorkspaceTabs />
                    </div>
                    <WorkflowNotificationCenter />
                </div>

                <main id="main-content" tabIndex={-1} className="min-h-[calc(100vh-4rem)]">
                    {children}
                </main>
            </div>

            {/* First-run LLM provider prompt (EPIC-023 PR4): app-wide so it
                surfaces wherever the user lands while unconfigured. */}
            <FirstRunModal />
        </div>
    );
}

export function AppShell({ children }: AppShellProps) {
    return (
        <WorkspaceProvider>
            <ToastProvider>
                <AppShellContent>{children}</AppShellContent>
            </ToastProvider>
        </WorkspaceProvider>
    );
}
