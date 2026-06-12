"use client";

import { ReactNode } from "react";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { Sidebar } from "@/components/Sidebar";
import { MobileNav } from "@/components/MobileNav";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { ToastProvider } from "@/components/ui/Toast";
import { WorkflowNotificationCenter } from "@/components/workflow/WorkflowNotifications";

interface AppShellProps {
    children: ReactNode;
}

function AppShellContent({ children }: AppShellProps) {
    const { isCollapsed } = useWorkspace();

    return (
        <div className="min-h-screen">
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

                <main className="min-h-[calc(100vh-4rem)]">
                    {children}
                </main>
            </div>
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
