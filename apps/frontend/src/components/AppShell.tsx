"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { useSessionBootstrap } from "@/hooks/useSessionBootstrap";
import { Sidebar } from "@/components/Sidebar";
import { BottomTabBar } from "@/components/shell/BottomTabBar";
import { InstallAppPrompt } from "@/components/pwa/InstallAppPrompt";
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
        <div className="pwa-safe-area-shell min-h-screen">
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
                    <Link
                        href="/"
                        className="flex items-center gap-2 px-3 py-2 md:hidden"
                        aria-label="Finance Report home"
                    >
                        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--accent)] text-sm font-bold text-white">
                            $
                        </span>
                    </Link>
                    <div className="hidden md:block min-w-0 flex-1">
                        <WorkspaceTabs />
                    </div>
                    <WorkflowNotificationCenter />
                </div>
                <InstallAppPrompt />

                {/* Bottom padding on mobile so the fixed bottom tab bar never
                    covers page content. */}
                <main
                    id="main-content"
                    tabIndex={-1}
                    className="min-h-[calc(100vh-4rem)] pb-20 md:pb-0"
                >
                    {children}
                </main>
            </div>

            {/* EPIC-022 AC22.21.2: mobile/PWA-first bottom tab bar. */}
            <BottomTabBar />

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
