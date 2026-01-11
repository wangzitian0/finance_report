"use client";

import { ReactNode } from "react";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { Sidebar } from "@/components/Sidebar";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";

interface AppShellProps {
    children: ReactNode;
}

function AppShellContent({ children }: AppShellProps) {
    const { isCollapsed } = useWorkspace();

    return (
        <div className="min-h-screen">
            <Sidebar />

            {/* Main Content Area */}
            <div
                className={`
          transition-all duration-300 ease-in-out
          ${isCollapsed ? "ml-16" : "ml-64"}
        `}
            >
                <WorkspaceTabs />

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
            <AppShellContent>{children}</AppShellContent>
        </WorkspaceProvider>
    );
}
