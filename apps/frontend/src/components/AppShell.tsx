"use client";

import { ReactNode } from "react";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { Sidebar } from "@/components/Sidebar";
import { MobileNav } from "@/components/MobileNav";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { ToastProvider } from "@/components/ui/Toast";

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
                className={`transition-all duration-300 ease-in-out ${
                    isCollapsed ? "md:ml-16" : "md:ml-64"
                }`}
            >
                <div className="flex min-w-0 items-center border-b border-border md:block md:border-none">
                    <MobileNav />
                    <div className="hidden md:block min-w-0">
                        <WorkspaceTabs />
                    </div>
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
